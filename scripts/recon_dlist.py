"""Capture the exact POST Playwright makes to dlist.php when the user checks a row."""
import asyncio, json
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        requests_log = []
        page.on("request", lambda r: requests_log.append({
            "method": r.method, "url": r.url,
            "post_data": r.post_data,
            "resource_type": r.resource_type,
            "headers": dict(r.headers),
        }))

        # 1. Accept disclaimer, load name.php, submit search
        await page.goto("https://search.jeffersondeeds.com/index.php?acceptDisclaimer=true",
                        wait_until="domcontentloaded")
        await page.goto("https://search.jeffersondeeds.com/name.php",
                        wait_until="domcontentloaded")
        await page.locator("input[name=param1]").fill("SMITH JOHN")
        await page.locator("input[name=search]").click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        # 2. Tick the first checkbox and click "View Names"
        print(f"On page: {page.url}")
        first_cb = page.locator("input[type=checkbox][id^=checkbox]").first
        if await first_cb.count():
            await first_cb.check()
            print("first checkbox ticked")
            cb_value = await first_cb.get_attribute("value")
            cb_id = await first_cb.get_attribute("id")
            print(f"  value = {cb_value}")
            print(f"  id    = {cb_id}")
        view_btn = page.locator("input[type=button][value='View Names']").first
        await view_btn.click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(3000)

        print(f"After View Names click, URL: {page.url}")
        html = await page.content()
        print(f"response HTML size: {len(html)}")
        import re
        forms = len(re.findall(r"<FORM ACTION=pdetail", html, re.IGNORECASE))
        print(f"  pdetail forms: {forms}")
        print(f"  HIT LIST: {'HIT LIST' in html}")
        print(f"  NO HITS:  {'NO HITS FOUND' in html}")

        # Save dlist response
        with open("output/jcd_dlist_live.html", "w", encoding="utf-8") as f:
            f.write(html)

        # Dump the request that hit dlist.php
        print()
        print("=== dlist.php POST data ===")
        for req in requests_log:
            if "dlist.php" in req["url"] and req["method"] == "POST":
                print(f"  url: {req['url']}")
                print(f"  POST data: {req['post_data']}")
                print(f"  Content-Type: {req['headers'].get('content-type', 'n/a')}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
