import asyncio
import os
from playwright.async_api import async_playwright

async def run():
    print("Launching browser...")
    async with async_playwright() as p:
        # Launch non-headless to see what happens, or headless if sandbox restricts
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        url = "https://higher.gs.com/"
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="load", timeout=30000)
        await page.wait_for_timeout(5000)
        
        # Let's check if there is a redirect
        current_url = page.url
        print(f"Current URL after redirect: {current_url}")
        
        # Apply filters or keyword searches
        # Wait, the career_pages configuration has:
        # {"action": "auto_search", "location": "India"}
        # Let's see what auto-search would do or if we can do search directly
        # Let's type "Bengaluru" into search if possible
        inputs = await page.locator("input").all()
        print(f"Found {len(inputs)} input fields:")
        for idx, inp in enumerate(inputs):
            visible = await inp.is_visible()
            placeholder = await inp.get_attribute("placeholder") or ""
            id_attr = await inp.get_attribute("id") or ""
            name_attr = await inp.get_attribute("name") or ""
            print(f"  Input {idx}: id='{id_attr}', name='{name_attr}', placeholder='{placeholder}', visible={visible}")
            
        # Let's screenshot to visually see the page state
        os.makedirs("scratch", exist_ok=True)
        await page.screenshot(path="scratch/gs_home.png")
        print("Saved scratch/gs_home.png")
        
        # Let's look for pagination elements:
        # oj-paging-control, next buttons, etc.
        buttons = await page.locator("button, a").all()
        print(f"Found {len(buttons)} total buttons/links.")
        
        # Look for buttons or links with pagination text or classes
        pag_buttons = []
        for btn in buttons:
            txt = (await btn.inner_text() or "").strip()
            class_attr = await btn.get_attribute("class") or ""
            aria_label = await btn.get_attribute("aria-label") or ""
            href = await btn.get_attribute("href") or ""
            
            # Match typical pagination terms
            is_pag = any(term in txt.lower() or term in class_attr.lower() or term in aria_label.lower() 
                         for term in ["next", "prev", "page", "paging", "load more", "show more", "forward", "chevron"])
            # Or if text is just a number
            if txt.isdigit():
                is_pag = True
                
            if is_pag:
                pag_buttons.append((txt, class_attr, aria_label, href))
                
        print(f"Found {len(pag_buttons)} potential pagination elements:")
        for idx, (txt, cls, aria, href) in enumerate(pag_buttons[:30]):
            print(f"  Pag Element {idx}: text='{txt}', class='{cls[:50]}', aria='{aria}', href='{href}'")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
