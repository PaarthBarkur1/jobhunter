import asyncio
from playwright.async_api import async_playwright

async def test_url(url):
    print(f"\nTesting URL: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=25000)
            await page.wait_for_timeout(4000)
            print(f"  Final URL: {page.url}")
            print(f"  Title: {await page.title()}")
            
            # Find open jobs counter
            body_text = await page.locator("body").inner_text()
            # Look for "Open Jobs" text
            import re
            matches = re.findall(r'\d+\s+Open\s+Jobs', body_text, re.IGNORECASE)
            print(f"  Matches for 'Open Jobs': {matches}")
            
            # Print a snippet of body text
            print("  Body text snippet:")
            print("\n".join(body_text.splitlines()[:15]))
        except Exception as e:
            print(f"  Error visiting {url}: {e}")
        finally:
            await browser.close()

async def main():
    urls = [
        "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs",
        "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs",
        "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1002/jobs",
        "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/jobs",
        "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CampusHiring/jobs"
    ]
    for url in urls:
        await test_url(url)

if __name__ == "__main__":
    asyncio.run(main())
