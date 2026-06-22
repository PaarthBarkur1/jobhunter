import asyncio
from playwright.async_api import async_playwright

async def run():
    url = "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.goto(url, wait_until="load")
        await page.wait_for_timeout(4000)
        
        # Search keyword: "Quantitative" and location: "India"
        await page.locator("input#keyword").first.fill("Quantitative")
        await page.locator("input#location").first.fill("India")
        await page.wait_for_timeout(1500)
        
        # Click suggestion
        option = page.locator("[role='option']").first
        if await option.is_visible():
            await option.click()
            
        await page.wait_for_timeout(500)
        
        # Click search
        await page.locator("button.search-box-compact__button").first.click()
        await page.wait_for_timeout(6000)
        
        # Take a screenshot to confirm jobs are listed
        await page.screenshot(path="scratch/gs_results_debug.png")
        print("Saved scratch/gs_results_debug.png")
        
        # Let's inspect all elements that contain text on the results page
        print("Checking text of h2, h3, h4 headers on the page:")
        headers = await page.locator("h2, h3, h4").all()
        for idx, h in enumerate(headers):
            txt = await h.inner_text()
            tag = await h.evaluate("el => el.tagName")
            print(f"  Header {idx}: tag={tag}, text='{txt.strip()}'")
            
        # Let's check for any links on the page
        links = await page.locator("a").all()
        print(f"Found {len(links)} <a> elements:")
        for idx, link in enumerate(links[:50]):
            href = await link.get_attribute("href") or ""
            text = await link.inner_text() or ""
            print(f"  Link {idx}: text='{text.strip()}', href='{href}'")
            
        # Check elements with class containing 'job' or 'title'
        print("Checking other elements that might be job postings:")
        job_els = await page.locator("[class*='job'], [class*='title'], [class*='requisition']").all()
        for idx, el in enumerate(job_els[:50]):
            cls = await el.get_attribute("class") or ""
            text = await el.inner_text() or ""
            id_attr = await el.get_attribute("id") or ""
            tag = await el.evaluate("el => el.tagName")
            if text.strip() and len(text.strip()) < 200:
                print(f"  El {idx}: tag={tag}, id='{id_attr}', class='{cls}', text='{text.strip()}'")
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
