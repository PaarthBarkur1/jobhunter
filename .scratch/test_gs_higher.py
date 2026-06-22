import asyncio
from playwright.async_api import async_playwright

async def run():
    url = "https://higher.gs.com"
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(5000)
        
        # Save screenshot
        await page.screenshot(path="scratch/gs_higher_land.png")
        print("Saved scratch/gs_higher_land.png")
        print(f"Current URL: {page.url}")
        print(f"Title: {await page.title()}")
        
        # Check inputs
        inputs = await page.locator("input").all()
        print(f"Found {len(inputs)} inputs:")
        for idx, inp in enumerate(inputs):
            placeholder = await inp.get_attribute("placeholder") or ""
            name_attr = await inp.get_attribute("name") or ""
            id_attr = await inp.get_attribute("id") or ""
            visible = await inp.is_visible()
            print(f"  Input {idx}: id='{id_attr}', name='{name_attr}', placeholder='{placeholder}', visible={visible}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
