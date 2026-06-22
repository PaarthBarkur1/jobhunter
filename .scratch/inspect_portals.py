import asyncio
from playwright.async_api import async_playwright

async def inspect_page(url, name):
    print(f"\n=== Inspecting {name}: {url} ===")
    async with async_playwright() as p:
        # Launch browser headlessly
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"Failed to load page with networkidle: {e}")
            try:
                await page.goto(url, wait_until="load", timeout=30000)
            except Exception as e2:
                print(f"Failed to load page with load: {e2}")
        
        await page.wait_for_timeout(3000)
        
        # Take a screenshot to visualize
        screenshot_path = f"scratch/{name.lower()}_initial.png"
        await page.screenshot(path=screenshot_path)
        print(f"Saved initial screenshot to {screenshot_path}")
        
        # Let's inspect inputs
        inputs = await page.locator("input").all()
        print(f"Found {len(inputs)} input fields:")
        for idx, inp in enumerate(inputs):
            placeholder = await inp.get_attribute("placeholder") or ""
            name_attr = await inp.get_attribute("name") or ""
            id_attr = await inp.get_attribute("id") or ""
            class_attr = await inp.get_attribute("class") or ""
            type_attr = await inp.get_attribute("type") or ""
            aria_label = await inp.get_attribute("aria-label") or ""
            visible = await inp.is_visible()
            print(f"  Input {idx}: id='{id_attr}', name='{name_attr}', placeholder='{placeholder}', aria-label='{aria_label}', type='{type_attr}', visible={visible}")
            
        # Let's look for search buttons
        buttons = await page.locator("button").all()
        print(f"Found {len(buttons)} button elements:")
        for idx, btn in enumerate(buttons):
            text = await btn.inner_text() or ""
            id_attr = await btn.get_attribute("id") or ""
            class_attr = await btn.get_attribute("class") or ""
            visible = await btn.is_visible()
            if text.strip() or id_attr:
                print(f"  Button {idx}: id='{id_attr}', text='{text.strip()}', visible={visible}")
                
        await browser.close()

async def main():
    gs_url = "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
    ebay_url = "https://jobs.ebayinc.com/us/en"
    
    await inspect_page(gs_url, "GoldmanSachs")
    await inspect_page(ebay_url, "eBay")

if __name__ == "__main__":
    asyncio.run(main())
