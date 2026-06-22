import asyncio
from playwright.async_api import async_playwright

async def run():
    url = "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CampusHiring/jobs"
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
        
        # Save screenshot
        await page.screenshot(path="scratch/gs_all_jobs.png")
        print("Saved scratch/gs_all_jobs.png")
        
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
            if "/job/" in href or "jobs" in href:
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
