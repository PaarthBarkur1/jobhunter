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
        print(f"Navigating directly to {url}...")
        await page.goto(url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(5000)
        
        # 1. Fill keyword
        keyword_selector = "input#position-query-search"
        print("Typing keyword 'Data Science'...")
        await page.locator(keyword_selector).first.fill("Data Science")
        await page.wait_for_timeout(1000)
        
        # 2. Fill location
        location_selector = "input#position-location-search"
        print("Typing location 'India'...")
        await page.locator(location_selector).first.fill("India")
        await page.wait_for_timeout(2000)
        
        # Select first option in dropdown
        try:
            # For Eightfold, let's see if there is a dropdown
            await page.keyboard.press("ArrowDown")
            await page.wait_for_timeout(500)
            await page.keyboard.press("Enter")
        except Exception as e:
            print(f"Error selecting option: {e}")
            
        await page.wait_for_timeout(1000)
        
        # Click search
        print("Clicking Search...")
        search_btn = page.locator("button:has-text('Search jobs')").first
        await search_btn.click()
        await page.wait_for_timeout(5000)
        
        # Save screenshot
        await page.screenshot(path="scratch/ms_all_jobs.png")
        print("Saved scratch/ms_all_jobs.png")
        
        # Let's see the text in the job list container or any headings/links
        headers = await page.locator("h2, h3, h4").all()
        print(f"Found {len(headers)} headers:")
        for idx, h in enumerate(headers):
            txt = await h.inner_text()
            tag = await h.evaluate("el => el.tagName")
            print(f"  Header {idx}: tag={tag}, text='{txt.strip()}'")
            
        links = await page.locator("a").all()
        print(f"Found {len(links)} <a> elements:")
        for idx, link in enumerate(links):
            href = await link.get_attribute("href") or ""
            text = await link.inner_text() or ""
            visible = await link.is_visible()
            if "job" in href or "careers" in href:
                print(f"  Link {idx}: text='{text.strip()}', href='{href}', visible={visible}")
                
        # Print first few elements that look like jobs
        job_cards = await page.locator("[class*='job']").all()
        print(f"Found {len(job_els := [el for el in job_cards if await el.is_visible()])} visible job-related elements:")
        for idx, el in enumerate(job_els[:10]):
            text = await el.inner_text()
            cls = await el.get_attribute("class")
            print(f"  Element {idx}: class='{cls}', text='{text.strip()[:100]}'")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
