import asyncio
from playwright.async_api import async_playwright

async def run():
    urls = [
        "https://www.goldmansachs.com/careers/professionals/",
        "https://www.goldmansachs.com/careers/programs-for-professionals/"
    ]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        for url in urls:
            print(f"\nVisiting {url}...")
            try:
                await page.goto(url, wait_until="load", timeout=30000)
                await page.wait_for_timeout(3000)
                
                # Print page title
                print(f"Title: {await page.title()}")
                
                # Get all links containing 'oracle' or 'experience' or 'hire' or 'professionals' or 'recruiting'
                links = await page.locator("a").all()
                print(f"Found {len(links)} total links. Filtering for candidate portals...")
                for idx, link in enumerate(links):
                    href = await link.get_attribute("href") or ""
                    text = await link.inner_text() or ""
                    visible = await link.is_visible()
                    if any(x in href.lower() for x in ["oracle", "fa.us2", "recruiting", "cx", "job", "professionals", "hiring", "apply"]):
                        print(f"  Link {idx}: text='{text.strip()}', href='{href}', visible={visible}")
            except Exception as e:
                print(f"Error visiting {url}: {e}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
