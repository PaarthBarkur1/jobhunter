import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import asyncio
import json

from career_scraper import scrape_company_careers, format_career_scrape_result
import browser_manager


async def run_companies(companies):
    for company in companies:
        print(f"--- Scraping {company} ---")
        try:
            res = await scrape_company_careers(company=company, role_keywords=None, max_jobs=50, get_browser_context=browser_manager.get_page)
            print(format_career_scrape_result(res))
        except Exception as e:
            print(f"Error scraping {company}: {e}")


def main():
    companies = sys.argv[1:] if len(sys.argv) > 1 else ["D. E. Shaw", "Uber"]
    asyncio.run(run_companies(companies))


if __name__ == '__main__':
    main()
