import asyncio
import os
import sys
import json
import logging

# Ensure workspace root is in path
sys.path.append(r"c:\Users\paart\OneDrive\Desktop\job-hunter-agent")

from career_scraper import scrape_company_careers, format_career_scrape_result

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("test_scrapers")

async def get_browser_context(p):
    config = {}
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
        except Exception:
            pass
    headless = True
    user_data_dir = ".browser_profile"
    
    context = await p.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=headless,
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"]
    )
    return context

async def run():
    keywords = ["data scientist", "quant researcher", "software engineer", "analyst"]
    
    for company in ["Goldman Sachs", "eBay", "Morgan Stanley"]:
        logger.info(f"========== Testing Scraper for {company} ==========")
        try:
            result = await scrape_company_careers(
                company=company,
                role_keywords=keywords,
                max_jobs=15,
                get_browser_context=get_browser_context
            )
            print(format_career_scrape_result(result))
        except Exception as e:
            logger.error(f"Error for {company}: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(run())
