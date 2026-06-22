import asyncio
import re
from playwright.async_api import async_playwright

async def inspect_gs():
    url = "https://hdpc.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
    print("\n=== Inspecting GS ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.goto(url, wait_until="load")
        await page.wait_for_timeout(3000)
        
        # Fill Keyword
        await page.locator("input#keyword").first.fill("Data Science")
        await page.wait_for_timeout(500)
        
        # Fill Location
        await page.locator("input#location").first.fill("India")
        await page.wait_for_timeout(1500)
        
        # Select first option in dropdown
        try:
            # We saw that [role='option'] matches suggestion items
            first_option = page.locator("[role='option']").first
            if await first_option.is_visible():
                print(f"Selecting location option: '{await first_option.inner_text()}'")
                await first_option.click()
            else:
                print("No option visible via [role='option'], trying keyboard")
                await page.locator("input#location").first.focus()
                await page.keyboard.press("ArrowDown")
                await page.keyboard.press("Enter")
        except Exception as e:
            print(f"Error selecting option: {e}")
            
        await page.wait_for_timeout(1000)
        
        # Click search
        # Let's find the search button. Let's list all button elements that might be the search button.
        buttons = await page.locator("button").all()
        search_btn = None
        for btn in buttons:
            text = await btn.inner_text() or ""
            cls = await btn.get_attribute("class") or ""
            aria = await btn.get_attribute("aria-label") or ""
            id_attr = await btn.get_attribute("id") or ""
            # Search buttons in Oracle HCM often have class containing 'search' or id containing 'search' or are aria-labeled
            if "search" in text.lower() or "search" in cls.lower() or "search" in aria.lower() or "search" in id_attr.lower():
                print(f"Potential search button: tag=button, id='{id_attr}', text='{text}', class='{cls}', aria-label='{aria}'")
                search_btn = btn
                break
                
        if not search_btn:
            # If no button found, let's look for search icons/divs/spans
            divs = await page.locator("div, span, a").all()
            for el in divs:
                cls = await el.get_attribute("class") or ""
                aria = await el.get_attribute("aria-label") or ""
                id_attr = await el.get_attribute("id") or ""
                text = await el.inner_text() or ""
                if "search" in cls.lower() or "search" in aria.lower() or "search" in id_attr.lower():
                    # Check if it has a click handler or looks like a button
                    tag = el.element_handle().json_value() # just get tag
                    # print(f"Potential search element: tag={el}, id='{id_attr}', class='{cls}', text='{text[:30]}'")
                    # Let's check if it's visible and we can click it
                    if await el.is_visible() and len(cls) > 0:
                        search_btn = el
                        break
                        
        if search_btn:
            print("Clicking found search button/element...")
            await search_btn.click()
        else:
            print("No search button found, pressing Enter on keyword field")
            await page.locator("input#keyword").first.press("Enter")
            
        await page.wait_for_timeout(5000)
        await page.screenshot(path="scratch/gs_results_detail.png")
        
        # Let's dump all links on the page now
        links = await page.locator("a").all()
        print(f"Total links after search: {len(links)}")
        for idx, link in enumerate(links):
            href = await link.get_attribute("href") or ""
            text = await link.inner_text() or ""
            visible = await link.is_visible()
            if href.strip() or text.strip():
                print(f"  Link {idx}: text='{text.strip()}', href='{href}', visible={visible}")
                
        await browser.close()

async def inspect_ebay():
    url = "https://jobs.ebayinc.com/us/en"
    print("\n=== Inspecting eBay ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=25000)
        except Exception as e:
            print(f"Navigation timed out: {e}")
            
        await page.wait_for_timeout(3000)
        
        # Let's see what inputs are there:
        # Input 0: id='typehead', name='typehead', placeholder='Search job title or location', visible=True
        # Let's type 'Data Scientist India' into it
        typeahead = page.locator("input#typehead").first
        if await typeahead.is_visible():
            print("Typing 'Data Scientist India' in #typehead...")
            await typeahead.fill("Data Scientist India")
            await page.wait_for_timeout(2000)
            
            # Press enter or check if a suggestion list is visible
            # Let's check for suggestions
            suggestions = await page.locator("[role='option'], .ph-search-suggestion, li.ui-menu-item").all()
            print(f"Found {len(suggestions)} autocomplete suggestions for eBay:")
            for idx, sug in enumerate(suggestions):
                text = await sug.inner_text()
                print(f"  Suggestion {idx}: '{text.strip()}'")
                
            # Let's press enter to search
            print("Pressing Enter to search...")
            await typeahead.press("Enter")
            await page.wait_for_timeout(5000)
            await page.screenshot(path="scratch/ebay_results.png")
            
            # Print all links on the search results page
            links = await page.locator("a").all()
            print(f"Total links after search on eBay: {len(links)}")
            for idx, link in enumerate(links):
                href = await link.get_attribute("href") or ""
                text = await link.inner_text() or ""
                visible = await link.is_visible()
                if "/job/" in href or "ebay" in href or "jobs.ebayinc.com" in href:
                    print(f"  Link {idx}: text='{text.strip()}', href='{href}', visible={visible}")
        else:
            print("No typehead input found on eBay page!")
            
        await browser.close()

async def main():
    await inspect_gs()
    await inspect_ebay()

if __name__ == "__main__":
    asyncio.run(main())
