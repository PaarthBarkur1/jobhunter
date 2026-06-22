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
            
            # Print visible inputs
            inputs = await page.locator("input").all()
            print(f"Found {len(inputs)} inputs. Visible ones:")
            for idx, inp in enumerate(inputs):
                if await inp.is_visible():
                    placeholder = await inp.get_attribute("placeholder") or ""
                    name_attr = await inp.get_attribute("name") or ""
                    id_attr = await inp.get_attribute("id") or ""
                    type_attr = await inp.get_attribute("type") or ""
                    class_attr = await inp.get_attribute("class") or ""
                    print(f"  Input {idx}: id='{id_attr}', name='{name_attr}', type='{type_attr}', placeholder='{placeholder}', class='{class_attr}'")
                    
            # Print visible buttons
            buttons = await page.locator("button").all()
            print(f"Found {len(buttons)} buttons. Visible ones:")
            for idx, btn in enumerate(buttons):
                if await btn.is_visible():
                    text = await btn.inner_text() or ""
                    class_attr = await btn.get_attribute("class") or ""
                    print(f"  Button {idx}: text='{text.strip()}', class='{class_attr}'")
                    
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
