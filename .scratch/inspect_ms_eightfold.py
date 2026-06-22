import asyncio
from playwright.async_api import async_playwright

async def run():
    url = "https://morganstanley.eightfold.ai/careers"
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=30000)
        except Exception as e:
            print(f"Navigation timed out: {e}")
        await page.wait_for_timeout(4000)
        
        # Take a screenshot to visualize
        await page.screenshot(path="scratch/ms_eightfold_initial.png")
        print("Saved scratch/ms_eightfold_initial.png")
        
        # Print all inputs
        inputs = await page.locator("input, select").all()
        print(f"Found {len(inputs)} inputs/selects on Morgan Stanley Eightfold page:")
        for idx, inp in enumerate(inputs):
            id_attr = await inp.get_attribute("id") or ""
            name_attr = await inp.get_attribute("name") or ""
            placeholder = await inp.get_attribute("placeholder") or ""
            visible = await inp.is_visible()
            tag = await inp.evaluate("el => el.tagName")
            print(f"  Input {idx}: tag={tag}, id='{id_attr}', name='{name_attr}', placeholder='{placeholder}', visible={visible}")
            
        # Check buttons
        buttons = await page.locator("button").all()
        print(f"Found {len(buttons)} buttons:")
        for idx, btn in enumerate(buttons):
            text = await btn.inner_text() or ""
            visible = await btn.is_visible()
            if text.strip():
                print(f"  Button {idx}: text='{text.strip()}', visible={visible}")
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
