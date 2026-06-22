import os
import json
import asyncio
from playwright.async_api import async_playwright

async def run_login_helper():
    config_path = "config.json"
    user_data_dir = ".browser_profile"
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
                user_data_dir = config.get("user_data_dir", ".browser_profile")
        except Exception as e:
            print(f"Error reading config.json: {e}")
            
    print(f"Starting headed browser session...")
    print(f"Browser profile will be saved in: {os.path.abspath(user_data_dir)}")
    print("----------------------------------------------------------------")
    print("INSTRUCTIONS:")
    print("1. A Chromium browser window will open.")
    print("2. Log in to your LinkedIn, Indeed, and Google/Bing accounts manually.")
    print("3. Solve any CAPTCHAs that appear.")
    print("4. Do NOT close the browser window manually.")
    print("5. Once you are successfully logged in, come back to this terminal and press ENTER to save and close.")
    print("----------------------------------------------------------------")
    
    async with async_playwright() as p:
        # Launch persistent context in headed mode
        # Disable automation features so sites don't easily block us
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome" if os.name == 'nt' else None, # Use local Chrome if available for max realism
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        # Open pages to log in
        page1 = await context.new_page()
        await page1.goto("https://www.linkedin.com/login")
        
        page2 = await context.new_page()
        await page2.goto("https://www.indeed.com/auth")
        
        page3 = await context.new_page()
        await page3.goto("https://www.google.com")
        
        page4 = await context.new_page()
        await page4.goto("https://www.bing.com")
        
        # Wait for user keypress in terminal
        await asyncio.get_event_loop().run_in_executor(None, input, "Press ENTER here when you have completed all logins...")
        
        # Close browser context to flush session files
        await context.close()
        print("Browser context closed successfully. Profile saved.")

if __name__ == "__main__":
    asyncio.run(run_login_helper())
