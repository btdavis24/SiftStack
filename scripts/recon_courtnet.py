"""Recon for KCOJ CourtNet 2.0 case-detail lookup (Phase 2c).

Goal: map the guest-access flow and find out what fields a probate case
detail page exposes without a paid subscription.

Source: https://kcoj.kycourts.net/CourtNet/Search/Index

Flow probed:
  1. Load the search page, capture terms-acceptance affordance
  2. Accept terms
  3. Submit case-number search
  4. Screenshot + HTML capture the detail page
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / "output" / "courtnet_recon"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://kcoj.kycourts.net/CourtNet"
INDEX_URL = f"{BASE}/Search/Index"


async def snapshot(page, label: str) -> None:
    ts = datetime.now().strftime("%H%M%S")
    prefix = OUT / f"{ts}_{label}"
    try:
        (prefix.with_suffix(".html")).write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(prefix.with_suffix(".png")), full_page=True)
    except Exception as e:
        print(f"  [snap] {label}: error {e}")
        return
    (prefix.with_suffix(".url.txt")).write_text(page.url + "\n", encoding="utf-8")
    print(f"  [snap] {label} -> {prefix.with_suffix('.png').name} @ {page.url}")


async def dump_controls(page) -> list[dict]:
    return await page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll(
                'input, select, textarea, button, a, form, [role="button"], [role="tab"]'
            )) {
                const rect = el.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;
                const item = {
                    tag: el.tagName.toLowerCase(),
                    type: el.type || null,
                    name: el.name || null,
                    id: el.id || null,
                    class: el.className || null,
                    action: el.action || null,
                    method: el.method || null,
                    href: el.href || null,
                    value: (el.value && el.type !== 'password') ? el.value : null,
                    placeholder: el.placeholder || null,
                    text: (el.innerText || '').slice(0, 100) || null,
                    visible,
                };
                if (visible || item.name || item.id) out.push(item);
            }
            return out;
        }"""
    )


async def main() -> None:
    print(f"Output dir: {OUT}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=200)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()

        page.on("request", lambda r: (print(f"  REQ  {r.method:5s} {r.url[:140]}")
                                     if r.resource_type in ("document", "xhr", "fetch") else None))
        page.on("response", lambda r: (print(f"  RESP {r.status} {r.url[:140]}")
                                       if r.request.resource_type in ("document", "xhr", "fetch") else None))

        print("-- Step 1: load index / terms --")
        await page.goto(INDEX_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        await snapshot(page, "01_index")
        controls = await dump_controls(page)
        (OUT / "01_index_controls.json").write_text(json.dumps(controls, indent=2), encoding="utf-8")

        # Look for a terms / accept / I agree affordance
        accept_candidates = await page.evaluate(
            """() => {
                const out = [];
                const re = /(accept|i agree|continue|terms)/i;
                document.querySelectorAll('button, input[type=submit], a').forEach(el => {
                    const t = (el.innerText || el.value || '').trim();
                    if (re.test(t)) {
                        out.push({
                            text: t.slice(0, 80),
                            tag: el.tagName.toLowerCase(),
                            type: el.type || null,
                            href: el.href || null,
                            id: el.id || null,
                            name: el.name || null,
                        });
                    }
                });
                return out;
            }"""
        )
        (OUT / "01_accept_candidates.json").write_text(json.dumps(accept_candidates, indent=2), encoding="utf-8")
        print(f"  Accept candidates: {len(accept_candidates)}")
        for c in accept_candidates[:5]:
            print(f"    {c}")

        # Try clicking any terms checkbox or the accept button
        print()
        print("-- Step 2: accept terms (if present) --")
        for cb in await page.locator("input[type=checkbox]").all():
            try:
                await cb.check()
            except Exception:
                pass
        for txt in ("I Agree", "Accept", "Continue", "Agree"):
            btn = page.locator(f"button:has-text('{txt}'), input[type=submit][value*='{txt}' i]").first
            if await btn.count():
                print(f"  Clicking '{txt}'")
                try:
                    await btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"  click failed: {e}")
                break
        await snapshot(page, "02_after_accept")

        # At this point the page should be the search form. Dump controls.
        controls = await dump_controls(page)
        (OUT / "02_search_controls.json").write_text(json.dumps(controls, indent=2), encoding="utf-8")
        # Log form actions / inputs
        forms = [c for c in controls if c["tag"] == "form"]
        inputs = [c for c in controls if c["tag"] in ("input", "select", "textarea")]
        print(f"  Forms: {len(forms)}")
        for f in forms[:5]:
            print(f"    {f.get('action')} (method={f.get('method')})")
        print(f"  Named inputs: {len([i for i in inputs if i.get('name')])}")
        for i in inputs[:15]:
            if i.get("name") or i.get("id"):
                print(f"    {i.get('tag')} name={i.get('name')} id={i.get('id')} type={i.get('type')} placeholder={i.get('placeholder')}")

        # Try a case-number search — enter a plausible KY probate number from
        # the 2025 docket. Format "YY-P-NNNNNN". If this returns "no results,"
        # we still learn the form mechanics.
        print()
        print("-- Step 3: case-number search --")
        test_case = "25-P-000001"  # likely exists — first probate of 2025
        # Try common input patterns: case number field, county selector
        for sel in (
            "input[name*='case' i]",
            "input[name*='Case' i]",
            "input[id*='case' i]",
            "input[id*='Case' i]",
            "input[placeholder*='case' i]",
        ):
            el = page.locator(sel).first
            if await el.count():
                try:
                    await el.fill(test_case)
                    print(f"  Filled case number via {sel}")
                    break
                except Exception as e:
                    print(f"  {sel} fill failed: {e}")

        # County selector (if present)
        for sel in ("select[name*='county' i]", "select[id*='county' i]"):
            el = page.locator(sel).first
            if await el.count():
                try:
                    await el.select_option(label="Jefferson")
                    print(f"  Selected Jefferson via {sel}")
                except Exception:
                    try:
                        await el.select_option(value="56")  # Jefferson's code on some KY portals
                    except Exception:
                        pass
                break

        # Submit
        for sel in ("button[type=submit]", "input[type=submit]",
                    "button:has-text('Search')"):
            btn = page.locator(sel).first
            if await btn.count():
                print(f"  Submitting via {sel}")
                try:
                    await btn.click()
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(3500)
                except Exception as e:
                    print(f"  submit failed: {e}")
                break
        await snapshot(page, "03_case_search_result")

        # If a result link is visible, click it
        print()
        print("-- Step 4: open first detail link (if any) --")
        detail = page.locator(
            "a[href*='Case'], a[href*='case'], a[href*='Detail']"
        ).first
        if await detail.count():
            href = await detail.get_attribute("href")
            print(f"  Detail href: {href}")
            try:
                await detail.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)
            except Exception as e:
                print(f"  click failed: {e}")
            await snapshot(page, "04_case_detail")
        else:
            print("  No detail link found.")

        # Dump cookies
        cookies = await ctx.cookies()
        (OUT / "04_cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        print(f"  Cookies: {[c['name'] for c in cookies]}")

        await browser.close()

    print("done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
