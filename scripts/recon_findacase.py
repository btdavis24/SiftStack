"""Recon the KY guest 'Find A Case' flow.

Flow (per user): kycourts.gov/Pages/index.aspx → click 'Find A Case' →
solve reCAPTCHA v2 via 2Captcha → search case records as guest.

Captures every intermediate page + cookies so we can build a headless
scraper afterwards.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
from playwright.async_api import async_playwright
from twocaptcha import TwoCaptcha

load_dotenv()

COURTNET_RECAPTCHA_SITEKEY = "6LeSYfwSAAAAALTmOl5RV_gvlPAyhpI6qSZN4Fk4"

OUT = Path(__file__).resolve().parent.parent / "output" / "findacase_recon"
OUT.mkdir(parents=True, exist_ok=True)


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
    print(f"  [snap] {label} -> {prefix.with_suffix('.png').name}")
    print(f"         URL: {page.url}")


async def dump_controls(page) -> list[dict]:
    return await page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll(
                'input, select, textarea, button, a, form, iframe'
            )) {
                const rect = el.getBoundingClientRect();
                const visible = rect.width > 0 && rect.height > 0;
                out.push({
                    tag: el.tagName.toLowerCase(),
                    type: el.type || null,
                    name: el.name || null,
                    id: el.id || null,
                    class: (el.className && typeof el.className === 'string') ? el.className.slice(0, 80) : null,
                    action: el.action || null,
                    method: el.method || null,
                    href: el.href || null,
                    src: el.src || null,
                    value: (el.value && el.type !== 'password') ? String(el.value).slice(0, 80) : null,
                    placeholder: el.placeholder || null,
                    text: (el.innerText || '').slice(0, 100) || null,
                    visible,
                });
            }
            return out;
        }"""
    )


async def main() -> None:
    print(f"Output dir: {OUT}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=400)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()

        page.on("request", lambda r: (print(f"  REQ  {r.method:5s} {r.url[:140]}")
                                     if r.resource_type in ("document", "xhr", "fetch") else None))
        page.on("response", lambda r: (print(f"  RESP {r.status} {r.url[:140]}")
                                       if r.request.resource_type in ("document", "xhr", "fetch") else None))

        # Capture response BODIES for any /Search/Search or /Case/ hits — those
        # are the data-bearing endpoints that drive the in-page result render.
        async def on_response(resp):
            url = resp.url
            if ("/Search/Search" in url or "/Case/" in url or
                "UiFormatCaseNumber" in url or "GetSearchCriteria" in url):
                try:
                    body = await resp.text()
                    fn = OUT / f"capture_{resp.request.method}_{url.split('/')[-1].split('?')[0][:40]}.txt"
                    fn.write_text(f"URL: {url}\n\n{body[:10000]}", encoding="utf-8")
                    print(f"  [capture] {resp.request.method} {url.split('?')[0][-60:]} -> {fn.name} ({len(body)} bytes)")
                except Exception as e:
                    print(f"  capture failed: {e}")
        page.on("response", on_response)

        print("-- Step 1: kycourts.gov landing --")
        await page.goto("https://www.kycourts.gov/Pages/index.aspx",
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        await snapshot(page, "01_kycourts_landing")

        # Locate the 'Find A Case' link
        candidates = await page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('a, button').forEach(el => {
                    const t = (el.innerText || '').toLowerCase();
                    if (/find\\s*a\\s*case/.test(t) || /case\\s*search/.test(t)) {
                        out.push({
                            text: el.innerText.slice(0, 80),
                            href: el.href || null,
                            tag: el.tagName.toLowerCase(),
                        });
                    }
                });
                return out;
            }"""
        )
        print(f"  Find-A-Case candidates: {len(candidates)}")
        for c in candidates[:5]:
            print(f"    {c}")
        (OUT / "01_findacase_candidates.json").write_text(
            json.dumps(candidates, indent=2), encoding="utf-8"
        )

        print()
        print("-- Step 2: navigate to Find A Case --")
        target = next((c["href"] for c in candidates if c.get("href")),
                      "https://kcoj.kycourts.net/kyecourts/login/guestlogin")
        print(f"  navigate -> {target}")
        await page.goto(target, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await snapshot(page, "02_after_findacase")

        # Look for Guest/Continue-as-Guest
        print()
        print("-- Step 3: look for guest-access affordance --")
        guest = await page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('a, button, input[type=submit]').forEach(el => {
                    const t = (el.innerText || el.value || '').toLowerCase();
                    if (/guest|continue|accept|terms|agree/.test(t)) {
                        out.push({
                            text: (el.innerText || el.value || '').slice(0, 80),
                            href: el.href || null,
                            tag: el.tagName.toLowerCase(),
                        });
                    }
                });
                return out;
            }"""
        )
        print(f"  guest candidates: {len(guest)}")
        for c in guest[:8]:
            print(f"    {c}")
        (OUT / "02_guest_candidates.json").write_text(json.dumps(guest, indent=2), encoding="utf-8")

        # Don't click Continue pre-solve — the reCAPTCHA data-callback="verify"
        # auto-submits via AJAX once the token is injected. Clicking Continue
        # here would GET the form action URL with an empty recaptcha-response
        # and dirty the URL.
        await snapshot(page, "03_before_captcha")

        # Look for CAPTCHA
        print()
        print("-- Step 4: detect CAPTCHA --")
        captcha_info = await page.evaluate(
            """() => {
                const result = {
                    recaptcha_iframes: [],
                    hcaptcha_iframes: [],
                    custom_captcha_imgs: [],
                    recaptcha_sitekeys: [],
                };
                document.querySelectorAll('iframe[src*=recaptcha]').forEach(i => result.recaptcha_iframes.push(i.src));
                document.querySelectorAll('iframe[src*=hcaptcha]').forEach(i => result.hcaptcha_iframes.push(i.src));
                document.querySelectorAll('img[src*=captcha], img[alt*=captcha]').forEach(i => result.custom_captcha_imgs.push(i.src));
                document.querySelectorAll('[data-sitekey]').forEach(el => result.recaptcha_sitekeys.push(el.getAttribute('data-sitekey')));
                return result;
            }"""
        )
        print(f"  CAPTCHA signals: {captcha_info}")
        (OUT / "03_captcha_info.json").write_text(json.dumps(captcha_info, indent=2), encoding="utf-8")

        controls = await dump_controls(page)
        (OUT / "03_post_guest_controls.json").write_text(json.dumps(controls, indent=2), encoding="utf-8")
        inputs = [c for c in controls if c["tag"] in ("input", "select") and (c.get("name") or c.get("id"))]
        print(f"  Named inputs on this page: {len(inputs)}")
        for i in inputs[:20]:
            print(f"    {i.get('tag'):<6s} name={i.get('name')!r:<25s} id={i.get('id')!r:<25s} type={i.get('type')}")

        # Print link to any obvious search action
        forms = [c for c in controls if c["tag"] == "form"]
        print(f"  Forms: {len(forms)}")
        for f in forms[:5]:
            print(f"    action={f.get('action')} method={f.get('method')}")

        print()
        print("-- Step 5: solve reCAPTCHA v2 via 2Captcha --")
        api_key = os.getenv("CAPTCHA_API_KEY", "")
        if not api_key:
            print("  CAPTCHA_API_KEY not set in .env — cannot auto-solve")
            print("  Pausing 120s for manual solve...")
            await page.wait_for_timeout(120_000)
        else:
            solver = TwoCaptcha(api_key)
            print(f"  Requesting 2Captcha solve (sitekey {COURTNET_RECAPTCHA_SITEKEY})")
            try:
                # 2Captcha's sync API blocks for ~15-30s while the solver works;
                # run it in a thread so the Playwright event loop stays responsive.
                result = await asyncio.to_thread(
                    solver.recaptcha,
                    sitekey=COURTNET_RECAPTCHA_SITEKEY,
                    url=page.url,
                )
                token = result.get("code") if isinstance(result, dict) else str(result)
                print(f"  Token received: {token[:40]}...")
            except Exception as e:
                print(f"  2Captcha error: {e}")
                token = ""

            if token:
                # The site's verify(token) callback does an AJAX POST to
                # /kyecourts/login/ValidateCaptcha and redirects on success.
                # Calling verify() directly bypasses the reCAPTCHA widget
                # entirely — no need to click Continue.
                print("  calling verify(token) to trigger server redirect")
                await page.evaluate("(token) => window.verify(token)", token)
                # Wait for redirect
                try:
                    await page.wait_for_url(
                        lambda url: "guestlogin" not in url, timeout=15000,
                    )
                except Exception:
                    pass
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2500)

        await snapshot(page, "04_after_captcha")
        controls2 = await dump_controls(page)
        (OUT / "04_post_captcha_controls.json").write_text(json.dumps(controls2, indent=2), encoding="utf-8")

        cookies = await ctx.cookies()
        (OUT / "04_cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        print(f"  Session cookies: {[c['name'] for c in cookies if c['name'] in ('.CNEAuthCookie','ASP.NET_SessionId','CourtNetProviderCookie')]}")

        # --- Step 6: Submit a case-number search ------------------------
        print()
        print("-- Step 6: Submit a real case-number search --")
        # Jefferson County code observed from the <select>; we'll pick by label.
        # Try a recent 25-P-* case. The existing kcoj_scraper memory notes
        # '26-P-001544' as a real case observed during Phase 1 recon.
        # Real case observed during Phase 1 KCOJ recon (see project memory)
        test_case = "26-P-001544"
        # The Case tab is a Bootstrap accordion section, collapsed by default.
        # Click "Search by Case" to expand it before filling fields.
        try:
            await page.locator("a.accordion-toggle:has-text('Search by Case')").click()
            await page.wait_for_timeout(800)
            print("  expanded 'Search by Case' accordion")
        except Exception as e:
            print(f"  accordion toggle failed: {e}")

        case_panel = page.locator("#searchByCase")

        # County uses a Select2 widget (the native select is display:none).
        # Click the display, then click the Jefferson option. Scope to the
        # Case panel so we don't accidentally hit the Party tab's selector.
        try:
            display = case_panel.locator(".select2-choice, .select2-container a").first
            await display.click()
            await page.wait_for_timeout(400)
            # Type into whichever select2 search field is currently focused
            await page.keyboard.type("jefferson")
            await page.wait_for_timeout(600)
            # Click the first result ("JEFFERSON")
            await page.locator(".select2-result-label:has-text('JEFFERSON')").first.click()
            print("  selected County=Jefferson via Select2")
        except Exception as e:
            print(f"  county Select2 failed: {e}")

        try:
            await case_panel.locator("input[name='SearchCriteria.CaseNumber']").fill(test_case)
            print(f"  filled CaseNumber={test_case}")
        except Exception as e:
            print(f"  case-number fill failed: {e}")

        submit = case_panel.locator("button[name='submit-case-search']").first
        if await submit.count():
            print("  submitting via button[name='submit-case-search']")
            try:
                await submit.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(4000)
            except Exception as e:
                print(f"  submit failed: {e}")
        await snapshot(page, "05_search_results")

        # --- Step 7: Open first case detail ----------------------------
        print()
        print("-- Step 7: Open first case detail --")
        detail = page.locator(
            "a[href*='Case/Detail'], a[href*='CaseDetail'], "
            "a[href*='Case/Index'], table a"
        ).first
        if await detail.count():
            href = await detail.get_attribute("href")
            print(f"  detail href: {href}")
            try:
                await detail.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3500)
                await snapshot(page, "06_case_detail")
                # Dump the full detail-page text so we can see what fields exist
                final_text = await page.inner_text("body")
                (OUT / "06_detail_text.txt").write_text(final_text, encoding="utf-8")
            except Exception as e:
                print(f"  detail click failed: {e}")
        else:
            print("  no detail link — search may have returned no hits")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
