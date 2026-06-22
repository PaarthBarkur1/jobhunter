"""Profile scraping runs and cache career page HTML to avoid re-scraping unchanged pages.

Behavior:
- For each company, fetch the career start URL (fast HTTP GET) and compute an HTML hash.
- If the HTML hasn't changed since last run (TTL respected), reuse cached job list and skip Playwright.
- If changed, run `scrape_company_careers` under `cProfile`, save stats to `profiles/{company}.prof`,
  and update the cache with the new job list and HTML hash.

This reduces repeated Playwright cold starts and only runs heavy scraping when the portal changed.
"""
import sys
import asyncio
from pathlib import Path

# Ensure repository root is on sys.path for local imports
sys.path.append(str(Path(__file__).resolve().parents[1]))
import cProfile
import hashlib
import json
import os
import time
from pathlib import Path

import http_client
import browser_manager
from career_scraper import scrape_company_careers
from career_pages import get_career_config, resolve_start_url


CACHE_PATH = Path("scratch/seen_jobs.json")
PROFILES_DIR = Path("profiles")
CACHE_TTL = 60 * 30  # 30 minutes


def load_cache():
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(data):
    CACHE_PATH.parent.mkdir(exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def html_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


async def do_scrape(company: str, keywords=None, max_jobs=50):
    return await scrape_company_careers(company=company, role_keywords=keywords, max_jobs=max_jobs, get_browser_context=browser_manager.get_page)


def profile_company(company: str, cache: dict):
    # Resolve start URL
    cfg = get_career_config(company)
    start_url = None
    if cfg:
        start_url = resolve_start_url(cfg)
    else:
        # try config.json mapping
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r", encoding="utf-8") as f:
                    app_conf = json.load(f)
                    start_url = app_conf.get("company_career_pages", {}).get(company)
            except Exception:
                start_url = None

    if not start_url:
        print(f"No start URL for {company}; skipping")
        return

    print(f"Checking {company} ({start_url})")
    # Fast fetch of start URL HTML
    try:
        resp = http_client.get(start_url)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"Failed to fetch start URL for {company}: {e}")
        html = ""

    h = html_hash(html)
    now = int(time.time())
    comp_cache = cache.get(company, {})
    last_hash = comp_cache.get("html_hash")
    last_time = comp_cache.get("last_checked", 0)

    # Decide whether to skip scraping
    if last_hash == h and (now - last_time) < CACHE_TTL:
        print(f"No change detected for {company}; reusing cached {len(comp_cache.get('jobs', []))} jobs")
        return

    # Changed: run profiler and scrape
    PROFILES_DIR.mkdir(exist_ok=True)
    prof_path = PROFILES_DIR / f"{company.replace(' ', '_')}.prof"
    pr = cProfile.Profile()
    pr.enable()
    try:
        result = asyncio.run(do_scrape(company))
    finally:
        pr.disable()
        pr.dump_stats(str(prof_path))

    jobs = result.get("jobs", []) if isinstance(result, dict) else []
    urls = [j.get("url") for j in jobs if j.get("url")]

    old_urls = comp_cache.get("urls", [])
    added = [u for u in urls if u not in old_urls]
    removed = [u for u in old_urls if u not in urls]

    comp_cache.update({
        "html_hash": h,
        "last_checked": now,
        "jobs": jobs,
        "urls": urls,
    })
    cache[company] = comp_cache
    save_cache(cache)

    print(f"Scraped {company}: {len(urls)} jobs (added {len(added)}, removed {len(removed)})")
    if added:
        print("Added:")
        for u in added:
            print(" - ", u)
    if removed:
        print("Removed:")
        for u in removed:
            print(" - ", u)


def main():
    companies = ["Goldman Sachs", "eBay", "Morgan Stanley"]
    cache = load_cache()
    for comp in companies:
        profile_company(comp, cache)


if __name__ == '__main__':
    main()
