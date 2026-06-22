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
            await page.wait_for_timeout(4000)
            
            # Fill keyword: software engineer
            await page.locator("input#position-query-search").first.fill("software engineer")
            await page.wait_for_timeout(500)
            
            # Fill location: India
            loc_input = page.locator("input#position-location-search").first
            await loc_input.fill("India")
            await page.wait_for_timeout(2000)
            
            # Click suggestion option
            try:
                options = await page.locator("[role='option'], [role='listbox'] li, .autocomplete-items div, .suggestion-item, li[id*='suggestion']").all()
                for opt in options:
                    if await opt.is_visible():
                        opt_text = (await opt.inner_text()).lower()
                        if "india" in opt_text:
                            print(f"Clicking option: '{await opt.inner_text()}'")
                            await opt.click()
                            break
            except Exception as sugg_err:
                print(f"Error clicking suggestion: {sugg_err}")
                
            await page.wait_for_timeout(1000)
            
            # Click search
            await page.locator("button:has-text('Search jobs')").first.click()
            await page.wait_for_timeout(6000)
            
            # Take screenshot of results
            await page.screenshot(path="scratch/ms_all_jobs.png")
            print("Saved scratch/ms_all_jobs.png")
            
            # Print body text summary
            body_text = await page.locator("body").inner_text()
            print("Snippet of body text after search:")
            print("\n".join(body_text.splitlines()[:25]))
            
            # Print all links that contain 'careers' or have '/job/' or have '?pid=' or look like jobs
            links = await page.locator("a").all()
            print(f"Found {len(links)} total links. Job-like links:")
            for idx, link in enumerate(links):
                href = await link.get_attribute("href") or ""
                text = await link.inner_text() or ""
                visible = await link.is_visible()
                if "pid=" in href or "/job/" in href or "careers?" in href or "careers" in href:
                    print(f"  Link {idx}: text='{text.strip()}', href='{href}', visible={visible}")
                    
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
