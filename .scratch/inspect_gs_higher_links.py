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
            
            # Print page title
            print(f"Title: {await page.title()}")
            
            # Print all links on the page that look like jobs or contain "/job/" or "/careers/" or "/role/" or "/opportunity/"
            links = await page.locator("a").all()
            print(f"Found {len(links)} total links. Job-like links:")
            for idx, link in enumerate(links):
                href = await link.get_attribute("href") or ""
                text = await link.inner_text() or ""
                # Print any link that is inside a heading or has a long text, or contains '/job/' or '/careers/'
                if any(x in href.lower() for x in ["/job/", "/role/", "/opportunity/", "/careers/", "higher.gs.com"]):
                    print(f"  Link {idx}: text='{text.strip()}', href='{href}'")
                elif text.strip() and len(text.strip()) > 10 and not href.startswith("#") and "apply" in href.lower():
                    print(f"  Link {idx}: text='{text.strip()}', href='{href}'")
                    
            # Let's also print headings of the cards
            # We see in the screenshot: "Engineering Division - AppBank - Analyst - Bengaluru"
            # Let's locate headings and their parent link elements
            h3s = await page.locator("h3").all()
            print(f"Found {len(h3s)} h3 elements:")
            for idx, h in enumerate(h3s):
                txt = await h.inner_text()
                # Find enclosing anchor or nearby anchor
                print(f"  H3 {idx}: '{txt.strip()}'")
                
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
