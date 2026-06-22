import sys
import asyncio
import json

sys.path.append(r"c:\Users\paart\OneDrive\Desktop\job-hunter-agent")

from career_scraper import scrape_company_careers
import browser_manager


async def gather(companies):
    all_jobs = []
    for company in companies:
        try:
            res = await scrape_company_careers(company=company, role_keywords=None, max_jobs=50, get_browser_context=browser_manager.get_page)
            for job in res.get('jobs', []):
                title = job.get('title', '').strip()
                url = job.get('url', '').strip()
                if title and url:
                    all_jobs.append((company, title, url))
        except Exception as e:
            print(f"Error scraping {company}: {e}")
    return all_jobs


def main():
    companies = ["Goldman Sachs", "eBay", "Morgan Stanley"]
    jobs = asyncio.run(gather(companies))
    for i, (company, title, url) in enumerate(jobs, 1):
        print(f"{i}. {company} — {title}\n   {url}")


if __name__ == '__main__':
    main()
