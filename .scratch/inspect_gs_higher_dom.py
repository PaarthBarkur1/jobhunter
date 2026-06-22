import asyncio
from playwright.async_api import async_playwright

async def run():
    url = "https://higher.gs.com/"
    print(f"Visiting {url}...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=30000)
            await page.wait_for_timeout(4000)
            
            # Find elements containing 'Bengaluru' or 'Engineering'
            elements = await page.locator("*:has-text('AppBank')").all()
            print(f"Found {len(elements)} elements containing 'AppBank'")
            
            for idx, el in enumerate(elements):
                tag = await el.evaluate("el => el.tagName")
                cls = await el.get_attribute("class") or ""
                inner_text = await el.inner_text()
                print(f"  El {idx}: tag={tag}, class='{cls}', text_len={len(inner_text)}, text='{inner_text.strip()[:150]}'")
                # Print outerHTML snippet of the element itself
                outer_html = await el.evaluate("el => el.outerHTML")
                print(f"    OuterHTML snippet: {outer_html[:300]}")
                    
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
