"""Authenticated recon for jeffersonpva.ky.gov.

Logs in with PVA_EMAIL / PVA_PASSWORD, probes the owner-search surface that
appears only after login, runs a sample owner-name search, and clicks into
a detail page. Saves HTML snapshots, screenshots, cookies, and a HAR file
so we can build a real scraper against the authenticated endpoints.

Writes everything to output/pva_recon/.

Run: python scripts/recon_pva.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

OUT = Path(__file__).resolve().parent.parent / "output" / "pva_recon"
OUT.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://jeffersonpva.ky.gov"
SEARCH_URL = f"{BASE_URL}/property-search/"

PVA_EMAIL = os.getenv("PVA_EMAIL", "")
PVA_PASSWORD = os.getenv("PVA_PASSWORD", "")

# Sample owner query. The form's placeholder example is "Doe John" —
# LAST FIRST, space-separated. Use a real decedent-style name to probe.
SAMPLE_OWNER_NAME = "SMITH JOHN"


async def dump_controls(page) -> list[dict]:
    """Inventory every interactive control on the current page."""
    return await page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll('select, input, textarea, button, a, form, [role="combobox"], [role="button"]')) {
                const rect = el.getBoundingClientRect();
                const item = {
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || null,
                    type: el.type || null,
                    name: el.name || null,
                    id: el.id || null,
                    class: el.className || null,
                    href: el.href || null,
                    action: el.action || null,
                    method: el.method || null,
                    placeholder: el.placeholder || null,
                    value: (el.value && el.type !== 'password') ? el.value : null,
                    aria_label: el.getAttribute('aria-label') || null,
                    text: (el.innerText || '').slice(0, 120) || null,
                    visible: rect.width > 0 && rect.height > 0,
                };
                if (item.visible || item.name || item.id || item.role) out.push(item);
            }
            return out;
        }"""
    )


async def snapshot(page, label: str) -> None:
    """Save HTML, screenshot, control inventory, and URL for a given step."""
    ts = datetime.now().strftime("%H%M%S")
    prefix = OUT / f"{ts}_{label}"
    html = await page.content()
    (prefix.with_suffix(".html")).write_text(html, encoding="utf-8")
    await page.screenshot(path=str(prefix.with_suffix(".png")), full_page=True)
    controls = await dump_controls(page)
    (prefix.with_suffix(".controls.json")).write_text(
        json.dumps(controls, indent=2), encoding="utf-8"
    )
    (prefix.with_suffix(".url.txt")).write_text(
        f"{page.url}\n", encoding="utf-8"
    )
    print(f"  [snapshot] {label}: {page.url}")
    print(f"    -> {prefix.with_suffix('.html').name}, .png, .controls.json")


async def main() -> None:
    if not PVA_EMAIL or not PVA_PASSWORD:
        print("ERROR: PVA_EMAIL / PVA_PASSWORD not set in .env", file=sys.stderr)
        sys.exit(1)

    print(f"PVA recon starting — output -> {OUT}")
    print(f"Login as: {PVA_EMAIL}")
    print(f"Sample search: owner name = '{SAMPLE_OWNER_NAME}'")
    print()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=250)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            record_har_path=str(OUT / "session.har"),
        )
        page = await context.new_page()

        # Log every navigation and form submission at the network level
        page.on(
            "request",
            lambda req: print(f"  REQ  {req.method:6s} {req.url[:140]}")
            if req.resource_type in ("document", "xhr", "fetch")
            else None,
        )
        page.on(
            "response",
            lambda resp: print(f"  RESP {resp.status} {resp.url[:140]}")
            if resp.request.resource_type in ("document", "xhr", "fetch")
            else None,
        )

        try:
            # ── Step 1: Landing page (logged out) ────────────────────
            print("── Step 1: Load property-search page (logged out) ──")
            await page.goto(SEARCH_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await snapshot(page, "01_landing_loggedout")

            # ── Step 2: Find login link ──────────────────────────────
            print("\n── Step 2: Locate login affordance ──")
            login_candidates = await page.evaluate(
                """() => {
                    const out = [];
                    const terms = ['log in', 'login', 'sign in', 'subscribe', 'account'];
                    document.querySelectorAll('a, button').forEach(el => {
                        const t = (el.innerText || '').toLowerCase().trim();
                        if (terms.some(term => t.includes(term))) {
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
            print(f"  Login candidates: {json.dumps(login_candidates, indent=2)}")
            (OUT / "02_login_candidates.json").write_text(
                json.dumps(login_candidates, indent=2), encoding="utf-8"
            )

            # ── Step 3: Click login, capture login page ──────────────
            print("\n── Step 3: Navigate to login ──")
            # Try the most likely candidate (first one with href)
            login_url = None
            for c in login_candidates:
                if c.get("href") and "login" in c["href"].lower():
                    login_url = c["href"]
                    break
            if not login_url:
                # Fallback: click by text
                login_link = page.locator(
                    "a:has-text('Log In'), a:has-text('Login'), a:has-text('Sign In')"
                ).first
                if await login_link.count():
                    login_url = await login_link.get_attribute("href")

            if login_url:
                print(f"  Navigating to login: {login_url}")
                await page.goto(login_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
            else:
                print("  No login link found — trying /login")
                await page.goto(f"{BASE_URL}/login/", wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

            await snapshot(page, "03_login_form")

            # ── Step 4: Submit login ─────────────────────────────────
            print("\n── Step 4: Submit credentials ──")
            # Jefferson PVA uses the Via Search Manager (VSM) plugin with
            # custom field names vsm_username / vsm_password.
            async def submit_login() -> None:
                await page.locator("input[name='vsm_username']").fill(PVA_EMAIL)
                await page.locator("input[name='vsm_password']").fill(PVA_PASSWORD)
                await page.locator("input[name='submit_login_form']").click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2500)

            await submit_login()
            print("  Submitted login form")

            # Session-limit handling: if the account is already logged in
            # elsewhere (1-concurrent-session subscription), the login page
            # re-renders with an "Active Sessions" table containing an
            # "End Session" button. Click it to evict the prior session,
            # then resubmit the login form.
            session_form = page.locator("form.end-session button[type='submit']").first
            if await session_form.count():
                print("  Session limit hit — clearing existing session")
                await session_form.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                # After clearing, re-submit login (form will be shown again)
                if await page.locator("input[name='vsm_username']").count():
                    await submit_login()
                    print("  Resubmitted login after session clear")

            await snapshot(page, "04_after_login")

            # Dump cookies — we need to know the session cookie name
            cookies = await context.cookies()
            (OUT / "04_cookies.json").write_text(
                json.dumps(cookies, indent=2), encoding="utf-8"
            )
            print(f"  Cookies set: {[c['name'] for c in cookies]}")

            # Verify auth succeeded — look for a Log Out link, account link,
            # or the disappearance of the login form.
            auth_ok = await page.evaluate(
                """() => {
                    const text = document.body.innerText.toLowerCase();
                    const hasLogout = text.includes('log out') || text.includes('logout') || text.includes('sign out');
                    const hasLoginForm = !!document.querySelector("input[name='vsm_username']");
                    return { hasLogout, hasLoginForm, url: location.href };
                }"""
            )
            print(f"  Auth check: {auth_ok}")
            if auth_ok["hasLoginForm"] and not auth_ok["hasLogout"]:
                print("  ! Still seeing login form — auth failed. Aborting.")
                return

            # ── Step 5: Return to property search (now authenticated) ─
            print("\n── Step 5: Load property-search page (authenticated) ──")
            await page.goto(SEARCH_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)
            await snapshot(page, "05_search_authenticated")

            # ── Step 6: Activate the owner-search tab (Bootstrap) ────
            print("\n── Step 6: Open owner-search tab ──")
            # Bootstrap tabs: click the nav link with data-toggle="tab".
            # URL anchor alone doesn't trigger the JS that un-hides the pane.
            await page.locator("a[href='#ownerSearch'][data-toggle='tab']").click()
            await page.wait_for_timeout(1500)
            await snapshot(page, "06_owner_tab_active")

            # Dump every visible input inside the owner-search panel
            owner_inputs = await page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('input, select, textarea, button, form').forEach(el => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 && rect.height === 0) return;
                        out.push({
                            tag: el.tagName.toLowerCase(),
                            type: el.type || null,
                            name: el.name || null,
                            id: el.id || null,
                            placeholder: el.placeholder || null,
                            value: (el.value && el.type !== 'password') ? el.value : null,
                            action: el.action || null,
                            method: el.method || null,
                            text: (el.innerText || '').slice(0, 100) || null,
                        });
                    });
                    return out;
                }"""
            )
            (OUT / "06_owner_form_inputs.json").write_text(
                json.dumps(owner_inputs, indent=2), encoding="utf-8"
            )

            # ── Step 7: Fill owner-search form and submit ─────────────
            print(f"\n── Step 7: Search owner = '{SAMPLE_OWNER_NAME}' ──")
            owner_input_selectors = [
                "input[name='psfldOwner']",
                "input[name='psfldOwnerName']",
                "input[name='psfldLastName']",
                "input[name='psfldFirstName']",
                "input[name='owner']",
                "input[placeholder*='owner' i]",
                "input[placeholder*='name' i]",
            ]
            owner_filled_sel = None
            for sel in owner_input_selectors:
                el = page.locator(sel).first
                if await el.count() and await el.is_visible():
                    await el.fill(SAMPLE_OWNER_NAME)
                    print(f"  Owner name filled via {sel}")
                    owner_filled_sel = sel
                    break

            if not owner_filled_sel:
                print("  ! No visible owner-name input found. Check 06_owner_form_inputs.json.")
                print("    Continuing anyway so we can inspect the form state.")
            await snapshot(page, "07_owner_form_filled")

            # Submit — the owner form's submit button. Scope to a visible one.
            submit = page.locator(
                "input[name='propertySearchFormButton']:visible, "
                "button[name='propertySearchFormButton']:visible, "
                "input[type='submit'][value*='Search' i]:visible"
            ).first
            if await submit.count():
                try:
                    await submit.click(timeout=10000)
                    print("  Submit clicked")
                except Exception as e:
                    print(f"  Submit click failed: {e}. Trying Enter on form input.")
                    if owner_filled_sel:
                        await page.locator(owner_filled_sel).first.press("Enter")
            else:
                print("  ! No visible submit button. Stopping before Step 8.")
                return

            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(3000)
            await snapshot(page, "08_owner_search_results")

            # Dump a flat table of every result row so we can see what the
            # listing format looks like (address, owner, parcel, etc.)
            rows = await page.evaluate(
                """() => {
                    const out = [];
                    // The WP plugin renders rows as divs with data attrs, or as table rows.
                    // Pull any element whose href starts with 'property-details'.
                    document.querySelectorAll('a[href*=\"property-details\"]').forEach(a => {
                        const row = a.closest('tr, li, .row, .property-result') || a.parentElement;
                        out.push({
                            href: a.href,
                            text: (row ? row.innerText : a.innerText).slice(0, 400),
                        });
                    });
                    return out.slice(0, 10);  // first 10 rows
                }"""
            )
            (OUT / "08_result_rows.json").write_text(
                json.dumps(rows, indent=2), encoding="utf-8"
            )
            print(f"  Result rows found: {len(rows)}")

            # ── Step 8: Click the first result to see detail page ────
            print("\n── Step 8: Open first result's detail page ──")
            detail_link = page.locator("a[href*='property-details']").first
            if await detail_link.count():
                href = await detail_link.get_attribute("href")
                print(f"  First detail link: {href}")
                await detail_link.click()
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)
                await snapshot(page, "09_detail_page")

                # Dump full-page text for easier value extraction later
                final_text = await page.inner_text("body")
                (OUT / "09_detail_text.txt").write_text(final_text, encoding="utf-8")

                # Dump all <dt>/<dd>, <th>/<td>, and labeled field pairs —
                # these are likely where "Assessed Value", "Parcel ID" etc. live.
                fields = await page.evaluate(
                    """() => {
                        const out = [];
                        document.querySelectorAll('dl').forEach(dl => {
                            const dts = dl.querySelectorAll('dt');
                            const dds = dl.querySelectorAll('dd');
                            for (let i = 0; i < Math.min(dts.length, dds.length); i++) {
                                out.push({type: 'dl', label: dts[i].innerText.trim(), value: dds[i].innerText.trim()});
                            }
                        });
                        document.querySelectorAll('table').forEach((t, idx) => {
                            t.querySelectorAll('tr').forEach(tr => {
                                const cells = tr.querySelectorAll('th, td');
                                if (cells.length === 2) {
                                    out.push({type: 'table' + idx, label: cells[0].innerText.trim(), value: cells[1].innerText.trim()});
                                }
                            });
                        });
                        return out;
                    }"""
                )
                (OUT / "09_detail_fields.json").write_text(
                    json.dumps(fields, indent=2), encoding="utf-8"
                )
                print(f"  Detail page fields extracted: {len(fields)}")
            else:
                print("  No detail link found on results page")

        finally:
            # Persist HAR + trace even on error
            await context.close()
            await browser.close()

    print(f"\n✓ Recon complete. Review {OUT}/")


if __name__ == "__main__":
    asyncio.run(main())
