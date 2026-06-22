import asyncio
from playwright.async_api import async_playwright

async def inspect():
    url = "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
    print("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="load")
        await page.wait_for_timeout(3000)
        
        # Print the HTML of the search box wrapper
        # Let's locate the parent of the input#keyword element
        keyword_input = page.locator("input#keyword")
        parent = page.locator("div.search-box-container, div[class*='search-box'], div[class*='searchbox']").first
        if await parent.is_visible():
            html = await parent.inner_html()
            print("=== Search Box Container HTML ===")
            print(html)
        else:
            # Print parent levels above input#keyword
            print("Search box container not found by class. Trailing parents of input#keyword:")
            html = await page.evaluate("""() => {
                const inp = document.getElementById('keyword');
                if (!inp) return 'input#keyword not found';
                let p = inp.parentElement;
                while (p && p.tagName !== 'BODY') {
                    if (p.className.includes('search') || p.className.includes('box')) {
                        return p.outerHTML;
                    }
                    p = p.parentElement;
                }
                return inp.parentElement.outerHTML;
            }""")
            print(html)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
