"""
Scrapes hardcoded company career portals using portal-specific strategies
and navigation instructions from career_pages.py.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import http_client

from career_pages import CareerPageConfig, get_career_config, resolve_start_url

logger = logging.getLogger("career_scraper")

ROLE_KEYWORDS_DEFAULT = [
    "data scientist",
    "applied scientist",
    "research scientist",
    "quant",
    "machine learning",
    "analytics",
]


def _matches_role(title: str, location: str, keywords: List[str]) -> bool:
    text = f"{title} {location}".lower()
    role_terms = set()
    for kw in keywords:
        role_terms.add(kw.lower())
        for part in re.split(r"[\s,/\-]+", kw.lower()):
            if len(part) > 3:
                role_terms.add(part)
    # Common synonyms for quant/data roles
    role_terms.update(["scientist", "science", "quant", "researcher", "analyst", "machine learning", "ml ", " ai"])
    return any(term in text for term in role_terms if len(term) > 2)


def _matches_india(location: str) -> bool:
    loc = location.lower()
    india_markers = [
        "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "gurugram",
        "gurgaon", "pune", "delhi", "ncr", "remote", "ind-",
    ]
    return any(m in loc for m in india_markers)


def _dedupe_jobs(jobs: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for job in jobs:
        url = job.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(job)
    return out


# ---------------------------------------------------------------------------
# ATS API scrapers (fast, reliable)
# ---------------------------------------------------------------------------

def _scrape_lever(cfg: CareerPageConfig, keywords: List[str], max_jobs: int) -> List[dict]:
    slug = cfg.ats_slug
    if not slug:
        return []
    api_url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        resp = http_client.get(api_url, timeout=15)
        resp.raise_for_status()
        postings = resp.json()
    except Exception as e:
        logger.warning(f"Lever API failed for {cfg.company}: {e}")
        return []

    jobs = []
    for post in postings:
        title = post.get("text", "")
        location = post.get("categories", {}).get("location", "")
        if not _matches_role(title, location, keywords):
            continue
        jobs.append({
            "title": title,
            "url": post.get("hostedUrl") or post.get("applyUrl", ""),
            "snippet": (post.get("descriptionPlain", "") or "")[:500],
            "company": cfg.company,
            "location": location,
            "source": "lever_api",
        })
        if len(jobs) >= max_jobs:
            break
    return jobs


def _scrape_greenhouse(cfg: CareerPageConfig, keywords: List[str], max_jobs: int) -> List[dict]:
    slug = cfg.ats_slug
    if not slug:
        return []
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        resp = http_client.get(api_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Greenhouse API failed for {cfg.company}: {e}")
        return []

    jobs = []
    for post in data.get("jobs", []):
        title = post.get("title", "")
        location = post.get("location", {}).get("name", "") if isinstance(post.get("location"), dict) else str(post.get("location", ""))
        if not _matches_role(title, location, keywords):
            continue
        jobs.append({
            "title": title,
            "url": post.get("absolute_url", ""),
            "snippet": (post.get("content", "") or "")[:500],
            "company": cfg.company,
            "location": location,
            "source": "greenhouse_api",
        })
        if len(jobs) >= max_jobs:
            break
    return jobs


def _scrape_rippling(cfg: CareerPageConfig, keywords: List[str], max_jobs: int) -> List[dict]:
    slug = cfg.ats_slug
    if not slug:
        return []
    api_url = f"https://ats.rippling.com/api/v2/board/{slug}/jobs"
    try:
        resp = http_client.get(api_url, params={"page": 0, "pageSize": 100}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"Rippling API failed for {cfg.company}: {e}")
        return []

    jobs = []
    for post in data.get("items", data.get("jobs", [])):
        title = post.get("title", post.get("name", ""))
        location = post.get("location", post.get("locationName", ""))
        if isinstance(location, dict):
            location = location.get("name", "")
        job_id = post.get("id", post.get("uuid", ""))
        url = post.get("url") or f"https://ats.rippling.com/{slug}/jobs/{job_id}"
        if not _matches_role(title, str(location), keywords):
            continue
        jobs.append({
            "title": title,
            "url": url,
            "snippet": (post.get("description", "") or "")[:500],
            "company": cfg.company,
            "location": str(location),
            "source": "rippling_api",
        })
        if len(jobs) >= max_jobs:
            break
    return jobs


# ---------------------------------------------------------------------------
# Playwright navigation scraper
# ---------------------------------------------------------------------------

async def _try_auto_search(page, keyword: str, location: str = "India"):
    """
    Dynamically scans the page for keyword and location input fields,
    fills them, handles autocompletion suggestions, and triggers search.
    """
    try:
        # Find all inputs
        inputs = await page.locator("input").all()
        
        kw_input = None
        loc_input = None
        
        # 1. Classify inputs
        for inp in inputs:
            if not await inp.is_visible():
                continue
            
            placeholder = (await inp.get_attribute("placeholder") or "").lower()
            aria_label = (await inp.get_attribute("aria-label") or "").lower()
            id_attr = (await inp.get_attribute("id") or "").lower()
            name_attr = (await inp.get_attribute("name") or "").lower()
            type_attr = (await inp.get_attribute("type") or "").lower()
            
            # Match location field
            if any(term in id_attr or term in name_attr or term in placeholder or term in aria_label 
                   for term in ["location", "city", "state", "country", "zip", "where"]):
                if not loc_input:
                    loc_input = inp
                    continue
            
            # Match keyword/search field
            if type_attr == "search" or any(term in id_attr or term in name_attr or term in placeholder or term in aria_label 
                   for term in ["keyword", "search", "title", "query", "role", "find", "job"]):
                if not kw_input:
                    kw_input = inp
        
        # If we didn't find specific ones, try defaults
        if not kw_input and inputs:
            # Maybe the first visible text input is keyword search?
            for inp in inputs:
                if await inp.is_visible() and (await inp.get_attribute("type") or "text") == "text":
                    kw_input = inp
                    break
        
        # 2. Fill inputs
        if kw_input:
            fill_text = keyword
            if not loc_input and location:
                fill_text = f"{keyword} {location}"
            logger.info(f"Auto-Search: Found keyword input. Filling with '{fill_text}'")
            await kw_input.fill(fill_text)
            await page.wait_for_timeout(500)
            
        if loc_input:
            logger.info(f"Auto-Search: Found location input. Filling with '{location}'")
            await loc_input.fill(location)
            await page.wait_for_timeout(1500) # Wait for suggestions
            
            # Try to handle suggestions/autocomplete
            try:
                options = await page.locator("[role='option'], [role='listbox'] li, .autocomplete-items div, .suggestion-item, li[id*='suggestion']").all()
                suggestion_clicked = False
                for opt in options:
                    if await opt.is_visible():
                        opt_text = (await opt.inner_text()).lower()
                        if location.lower() in opt_text:
                            logger.info(f"Auto-Search: Clicking suggestion option '{await opt.inner_text()}'")
                            await opt.click()
                            suggestion_clicked = True
                            break
                
                if not suggestion_clicked:
                    logger.info("Auto-Search: No matching location suggestion clicked. Trying keyboard dropdown select...")
                    await loc_input.focus()
                    await page.keyboard.press("ArrowDown")
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Enter")
            except Exception as sugg_err:
                logger.warning(f"Auto-Search: Error handling suggestion dropdown: {sugg_err}")
                
            await page.wait_for_timeout(500)

        # 3. Trigger Search
        search_clicked = False
        if kw_input or loc_input:
            # Find search button
            buttons = await page.locator("button, input[type='submit'], input[type='button']").all()
            for btn in buttons:
                if not await btn.is_visible():
                    continue
                
                text = (await btn.inner_text() or "").lower()
                cls = (await btn.get_attribute("class") or "").lower()
                aria = (await btn.get_attribute("aria-label") or "").lower()
                id_attr = (await btn.get_attribute("id") or "").lower()
                val = (await btn.get_attribute("value") or "").lower()
                
                if any(term in text or term in cls or term in aria or term in id_attr or term in val
                       for term in ["search", "find", "submit", "go"]):
                    if any(term in text or term in aria for term in ["clear", "near"]):
                        continue
                    logger.info(f"Auto-Search: Clicking search button with text '{await btn.inner_text()}'")
                    await btn.click()
                    search_clicked = True
                    break
                    
            if not search_clicked:
                logger.info("Auto-Search: No search button clicked. Pressing Enter in input...")
                target_input = kw_input or loc_input
                if target_input:
                    await target_input.focus()
                    await page.keyboard.press("Enter")
                    search_clicked = True
                    
        if search_clicked:
            await page.wait_for_timeout(4000)
            
    except Exception as e:
        logger.error(f"Auto-Search failed: {e}")


async def _execute_navigation(page, cfg: CareerPageConfig, keyword: str):
    """Run configured navigation steps on a Playwright page."""
    start_url = resolve_start_url(cfg)
    for step in cfg.navigation_steps:
        action = step.get("action")
        if action == "goto":
            url = step["url"].format(
                career_url=cfg.career_url,
                india_url=cfg.india_url or cfg.career_url,
                keyword=keyword,
            )
            await page.goto(url, wait_until="load", timeout=25000)
        elif action == "wait":
            await page.wait_for_timeout(step.get("ms", 2000))
        elif action == "scroll":
            times = step.get("times", 3)
            pause = step.get("pause_ms", 600)
            for _ in range(times):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(pause)
        elif action == "fill_if_visible":
            selector = step["selector"]
            text = step.get("text", "").format(keyword=keyword)
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    await el.fill(text)
            except Exception:
                pass
        elif action == "click_if_visible":
            selector = step["selector"]
            max_clicks = step.get("max_clicks", 1)
            for _ in range(max_clicks):
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=1500):
                        await el.click()
                        await page.wait_for_timeout(1000)
                    else:
                        break
                except Exception:
                    break
        elif action == "press":
            try:
                await page.keyboard.press(step.get("key", "Enter"))
            except Exception:
                pass
        elif action == "auto_search":
            location = step.get("location", "India")
            await _try_auto_search(page, keyword, location)


def _extract_links_from_html(html: str, base_url: str, cfg: CareerPageConfig) -> List[dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    patterns = [re.compile(p, re.I) for p in cfg.job_link_patterns]

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith("/"):
            href = urljoin(base_url, href)
        if not href.startswith("http"):
            continue
        matched = any(p.search(href) for p in patterns) if patterns else False
        if not matched:
            continue
        title = anchor.get_text(strip=True)
        if len(title) < 3 or title.lower() in ("apply", "learn more", "read more", "search"):
            parent = anchor.parent
            if parent:
                title_el = parent.find(class_=lambda c: c and any(x in c.lower() for x in ["title", "name", "heading", "header"]))
                if title_el:
                    title = title_el.get_text(strip=True)
                else:
                    lines = [line.strip() for line in parent.get_text("\n").split("\n") if line.strip()]
                    if lines:
                        title = lines[0]
        title = re.sub(r'\s+', ' ', title).strip()
        if len(title) < 3 or title.lower() in ("apply", "learn more", "read more", "search"):
            continue
        jobs.append({
            "title": title[:200],
            "url": href.split("#")[0],
            "snippet": "",
            "company": cfg.company,
            "location": "",
            "source": "career_portal",
        })
    return jobs


async def _scrape_with_playwright(cfg: CareerPageConfig, keywords: List[str], max_jobs: int, get_browser_context) -> List[dict]:

    # To be extremely efficient and respect the page's location/search filters,
    # if the config uses a location filter (like auto_search or india_url) or pagination,
    # we run a single search with an empty keyword. This utilizes the portal's built-in location filter (e.g. Bengaluru) to load all jobs.
    use_location_only = (
        cfg.india_url is not None or 
        any(step.get("action") == "auto_search" for step in cfg.navigation_steps) or
        cfg.pagination_selector is not None
    )

    all_jobs = []

    # `get_browser_context` is expected to be an async context manager that yields a Page
    # (see browser_manager.get_page). This avoids repeatedly launching Playwright.
    # Try the newer interface first: `get_browser_context()` should be an async
    # context manager that yields a `Page` (browser_manager.get_page).
    try:
        async with get_browser_context() as page:
            if use_location_only:
                logger.info("Using browser_manager-style page provider")
                logger.info(f"Using location/portal filters for '{cfg.company}' to scrape efficiently...")
                await _execute_navigation(page, cfg, "")

                # Extract initial page
                html = await page.content()
                all_jobs.extend(_extract_links_from_html(html, page.url, cfg))

                # Paginate if selector is available
                if cfg.pagination_selector:
                    current_page = 1
                    max_p = cfg.max_pages or 20
                    while current_page < max_p:
                        try:
                            next_btn = page.locator(cfg.pagination_selector).first
                            if await next_btn.is_visible() and await next_btn.is_enabled():
                                logger.info(f"Paginating to page {current_page + 1} for '{cfg.company}'...")
                                await next_btn.click()
                                await page.wait_for_timeout(2000)
                                try:
                                    await page.wait_for_load_state("networkidle", timeout=3000)
                                except Exception:
                                    pass

                                html = await page.content()
                                new_jobs = _extract_links_from_html(html, page.url, cfg)
                                if not new_jobs:
                                    logger.info("No more jobs found on next page. Stopping pagination.")
                                    break

                                existing_urls = {j["url"] for j in all_jobs}
                                if all(j["url"] in existing_urls for j in new_jobs):
                                    logger.info("All jobs on this page are duplicates. Stopping pagination.")
                                    break

                                all_jobs.extend(new_jobs)
                                current_page += 1
                            else:
                                logger.info("Pagination next button not visible/enabled. Stopping pagination.")
                                break
                        except Exception as e:
                            logger.warning(f"Error during pagination loop: {e}")
                            break
            else:
                # Fallback: standard keyword-by-keyword search
                keyword = keywords[0] if keywords else "data scientist"
                await _execute_navigation(page, cfg, keyword)
                html = await page.content()
                all_jobs.extend(_extract_links_from_html(html, page.url, cfg))

                # Try additional keyword searches on same portal
                # Run up to 2 additional searches but avoid long sequential waits
                for kw in keywords[1:3]:
                    await _execute_navigation(page, cfg, kw)
                    html = await page.content()
                    all_jobs.extend(_extract_links_from_html(html, page.url, cfg))
    except TypeError:
        # Fallback for older callers that expect a `(playwright)` -> context function
        logger.info("get_browser_context() did not accept zero args; falling back to legacy playwright flow")
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                context = await get_browser_context(p)
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    if use_location_only:
                        await _execute_navigation(page, cfg, "")
                        html = await page.content()
                        all_jobs.extend(_extract_links_from_html(html, page.url, cfg))
                    else:
                        keyword = keywords[0] if keywords else "data scientist"
                        await _execute_navigation(page, cfg, keyword)
                        html = await page.content()
                        all_jobs.extend(_extract_links_from_html(html, page.url, cfg))
                        for kw in keywords[1:3]:
                            await _execute_navigation(page, cfg, kw)
                            html = await page.content()
                            all_jobs.extend(_extract_links_from_html(html, page.url, cfg))
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Playwright scraping failed for {cfg.company}: {e}")
    except Exception as e:
        logger.error(f"Playwright scraping failed for {cfg.company}: {e}")

    # Filter by role keywords in title
    filtered = []
    for job in _dedupe_jobs(all_jobs):
        if _matches_role(job["title"], job.get("location", ""), keywords) or not keywords:
            filtered.append(job)
    return filtered[:max_jobs]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def scrape_company_careers(
    company: str,
    role_keywords: Optional[List[str]] = None,
    max_jobs: int = 15,
    get_browser_context=None,
) -> dict:
    """
    Scrape a company's hardcoded career portal.
    Returns {company, career_url, portal_type, navigation_instructions, jobs: [...]}
    """
    cfg = get_career_config(company)
    if not cfg:
        # Fallback: check if we have a user-defined URL mapping in config.json
        import json
        import os
        career_url = None
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r", encoding="utf-8") as f:
                    app_config = json.load(f)
                    career_url = app_config.get("company_career_pages", {}).get(company)
            except Exception:
                pass
                
        if not career_url:
            return {
                "company": company,
                "error": f"No hardcoded career page and no user URL mapping in config.json for '{company}'.",
                "jobs": [],
            }
            
        # Dynamically determine portal type
        portal_type = "custom"
        ats_slug = None
        
        # Check for greenhouse / lever / rippling in URL
        if "greenhouse.io" in career_url:
            portal_type = "greenhouse"
            match = re.search(r'greenhouse\.io/([^/?#\s]+)', career_url)
            if match:
                ats_slug = match.group(1)
        elif "lever.co" in career_url:
            portal_type = "lever"
            match = re.search(r'lever\.co/([^/?#\s]+)', career_url)
            if match:
                ats_slug = match.group(1)
        elif "rippling.com" in career_url:
            portal_type = "rippling"
            match = re.search(r'rippling\.com/([^/?#\s]+)', career_url)
            if match:
                ats_slug = match.group(1)
                
        cfg = CareerPageConfig(
            company=company,
            career_url=career_url,
            portal_type=portal_type,
            ats_slug=ats_slug,
            job_link_patterns=[
                r"/jobs/\d+", r"/jobs/[^/]+", r"/job/\d+", r"/careers/\d+",
                r"greenhouse\.io", r"lever\.co", r"/careers/[^/]+", r"/opportunities/[^/]+",
                r"/careersection/", r"/jobs/[^/]+/\d+"
            ],
            navigation_steps=[
                {"action": "goto", "url": "{career_url}"},
                {"action": "wait", "ms": 4000},
                {"action": "auto_search"},
                {"action": "wait", "ms": 3000},
                {"action": "scroll", "times": 5, "pause_ms": 600},
            ],
            model_instructions=f"Dynamic generic crawling for {company} based on user URL."
        )

    keywords = role_keywords or ROLE_KEYWORDS_DEFAULT
    jobs: List[dict] = []

    # Fast path: known ATS APIs
    if cfg.portal_type == "lever" and cfg.ats_slug:
        jobs = _scrape_lever(cfg, keywords, max_jobs)
    elif cfg.portal_type == "greenhouse" and cfg.ats_slug:
        jobs = _scrape_greenhouse(cfg, keywords, max_jobs)
    elif cfg.portal_type == "rippling" and cfg.ats_slug:
        jobs = _scrape_rippling(cfg, keywords, max_jobs)
    elif cfg.portal_type == "custom_uber":
        # Uber Freight posts on Greenhouse — supplement main portal
        freight_cfg = CareerPageConfig(
            company=cfg.company,
            career_url=cfg.career_url,
            portal_type="greenhouse",
            ats_slug="uberfreight",
        )
        jobs = _scrape_greenhouse(freight_cfg, keywords, max_jobs)

    # Browser path for custom/workday/google/etc.
    if len(jobs) < max_jobs and get_browser_context is not None:
        try:
            browser_jobs = await _scrape_with_playwright(cfg, keywords, max_jobs - len(jobs), get_browser_context)
            jobs.extend(browser_jobs)
        except Exception as e:
            logger.error(f"Playwright career scrape failed for {cfg.company}: {e}")

    jobs = _dedupe_jobs(jobs)[:max_jobs]

    return {
        "company": cfg.company,
        "career_url": resolve_start_url(cfg),
        "portal_type": cfg.portal_type,
        "navigation_instructions": cfg.model_instructions.strip(),
        "jobs_found": len(jobs),
        "jobs": jobs,
    }


def format_career_scrape_result(result: dict) -> str:
    """Format scrape result as text for MCP tool response."""
    if result.get("error"):
        return result["error"]

    lines = [
        f"Company: {result['company']}",
        f"Career URL: {result['career_url']}",
        f"Portal Type: {result['portal_type']}",
        f"Jobs Found: {result['jobs_found']}",
        "",
        "Navigation Instructions:",
        result.get("navigation_instructions", ""),
        "",
        "Job Listings:",
    ]
    for i, job in enumerate(result.get("jobs", []), 1):
        lines.append(f"Job {i}:")
        lines.append(f"  Title: {job.get('title', 'N/A')}")
        lines.append(f"  URL: {job.get('url', 'N/A')}")
        if job.get("location"):
            lines.append(f"  Location: {job['location']}")
        if job.get("snippet"):
            lines.append(f"  Snippet: {job['snippet'][:300]}")
        lines.append("")
    return "\n".join(lines)
