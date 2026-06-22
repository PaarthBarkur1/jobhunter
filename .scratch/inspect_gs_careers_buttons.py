import asyncio
from playwright.async_api import async_playwright

async def run():
    url = "https://www.goldmansachs.com/careers/"
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
            
            # Print page title
            print(f"Title: {await page.title()}")
            
            # Print all links on the page
            links = await page.locator("a").all()
            print(f"Found {len(links)} total links:")
            for idx, link in enumerate(links):
                href = await link.get_attribute("href") or ""
                text = await link.inner_text() or ""
                if text.strip() or "apply" in href.lower() or "job" in href.lower() or "career" in href.lower():
                    print(f"  Link {idx}: text='{text.strip()}', href='{href}'")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
