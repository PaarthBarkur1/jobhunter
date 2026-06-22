import asyncio
from playwright.async_api import async_playwright
import re
from urllib.parse import urljoin

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
        
        # We fill keyword 'analyst' (which should have jobs)
        await page.locator("input#keyword").first.fill("analyst")
        await page.locator("input#location").first.fill("India")
        await page.wait_for_timeout(1500)
        
        option = page.locator("[role='option']").first
        if await option.is_visible():
            await option.click()
        await page.wait_for_timeout(500)
        
        # Click search
        await page.locator("button.search-box-compact__button").first.click()
        await page.wait_for_timeout(6000)
        
        html = await page.content()
        print(f"Page title: {await page.title()}")
        print(f"URL: {page.url}")
        
        # Check if "0 Open Jobs" or similar text is there
        body_text = await page.locator("body").inner_text()
        print(f"Contains '0 Open Jobs': {'0 Open Jobs' in body_text}")
        print(f"Contains 'No results': {'No results' in body_text}")
        
        # Print first 200 chars of body text
        print("Body text snippet:")
        print(body_text[:500])
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        print("All links found:")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            title = anchor.get_text(strip=True)
            print(f"  Anchor: href='{href}', text='{title}'")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
