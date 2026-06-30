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
    if not keywords:
        return True
    text = f"{title} {location}".lower()
    for kw in keywords:
        kw_lower = kw.lower()
        # Use substring match rather than strict word boundaries
        # because scraped data often smashes words together (e.g., 'iconSoftware Engineer')
        if kw_lower in text:
            return True
    return False

def _matches_location(location: str, target_location: str) -> bool:
    if not target_location:
        return True
    loc_lower = location.lower()
    t_loc = target_location.lower()
    if "remote" in loc_lower or "anywhere" in loc_lower:
        return True
    return t_loc in loc_lower

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

def _scrape_lever(cfg: CareerPageConfig, keywords: List[str], target_location: str, max_jobs: int) -> List[dict]:
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
        if not _matches_role(title, location, keywords) or not _matches_location(location, target_location):
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


def _scrape_greenhouse(cfg: CareerPageConfig, keywords: List[str], target_location: str, max_jobs: int) -> List[dict]:
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
        if not _matches_role(title, location, keywords) or not _matches_location(location, target_location):
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


def _scrape_rippling(cfg: CareerPageConfig, keywords: List[str], target_location: str, max_jobs: int) -> List[dict]:
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
        if not _matches_role(title, str(location), keywords) or not _matches_location(str(location), target_location):
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

async def _try_auto_search(page, keyword: str, location: str):
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


async def _execute_navigation(page, cfg: CareerPageConfig, keyword: str, target_location: str = ""):
    """Run configured navigation steps on a Playwright page."""
    start_url = resolve_start_url(cfg)
    for step in cfg.navigation_steps:
        action = step.get("action")
        if action == "goto":
            url = step["url"].format(
                career_url=cfg.career_url,
                regional_url=cfg.regional_url or cfg.career_url,
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
            await _try_auto_search(page, keyword, location=target_location)


async def _extract_jobs_with_llm(html: str, base_url: str, cfg: CareerPageConfig, keywords: List[str]) -> List[dict]:
    from bs4 import BeautifulSoup
    import ollama
    import asyncio
    
    soup = BeautifulSoup(html, "html.parser")
    
    links = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith("/"):
            href = urljoin(base_url, href)
        if not href.startswith("http"): continue
        if href in seen: continue
        
        title = anchor.get_text(strip=True)
        title = re.sub(r'\s+', ' ', title).strip()
        if len(title) < 3 or title.lower() in ("apply", "learn more", "read more", "search", "cookie policy", "privacy policy"):
            continue
            
        links.append({"title": title[:200], "url": href.split("#")[0]})
        seen.add(href)
        
    if not links:
        return []
        
    # Get ollama config
    try:
        with open("config.json", "r") as f:
            global_config = json.load(f)
    except:
        global_config = {}
    model_name = global_config.get("ollama_model", "deepseek-r1:1.5b")
    host = global_config.get("ollama_host", "http://127.0.0.1:11434")
    
    client = ollama.AsyncClient(host=host)
    
    prompt_links = links
    if len(prompt_links) > 40:
        # Pre-filter to prioritize relevant roles and avoid context window truncation
        kws = [k.lower() for k in keywords] + ["engineer", "developer", "quant", "data", "analyst", "scientist", "research", "tech"]
        filtered = [l for l in prompt_links if any(kw in l["title"].lower() or kw in l["url"].lower() for kw in kws)]
        if len(filtered) > 5:
            prompt_links = filtered
    prompt_links = prompt_links[:40] # Cap to prevent context overflow
    
    roles_str = ", ".join(keywords) if keywords else "software, engineering, AI, or quant"
    prompt = f"You are an AI web navigator. Here are links found on {cfg.company}'s career page. Return a JSON list of ONLY the URLs that represent individual job postings matching these roles: {roles_str}. Output ONLY a raw JSON array of strings, like [\"url1\", \"url2\"].\n\nLinks:\n"
    for i, link in enumerate(prompt_links):
        title = link['title']
        if len(title) > 60:
            title = title[:57] + "..."
        prompt += f"{i+1}. {title} - {link['url']}\n"
        
    try:
        resp = await asyncio.wait_for(
            client.chat(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                options={"num_ctx": 4096, "num_predict": 1024}
            ),
            timeout=60
        )
        content = resp['message']['content']
        try:
            valid_urls = json.loads(content)
            if isinstance(valid_urls, dict):
                for v in valid_urls.values():
                    if isinstance(v, list):
                        valid_urls = v
                        break
            if not isinstance(valid_urls, list):
                valid_urls = []
        except Exception:
            valid_urls = []
            
        jobs = []
        for link in links:
            if link["url"] in valid_urls:
                jobs.append({
                    "title": link["title"],
                    "url": link["url"],
                    "snippet": "Discovered via LLM web navigator.",
                    "company": cfg.company,
                    "location": "",
                    "source": "career_portal"
                })
        logger.info(f"LLM Navigator found {len(jobs)} valid job URLs out of {len(links)} links on {cfg.company} page.")
        
        # If the LLM returns absolutely nothing but there were matching links, 
        # it might have hallucinated or over-filtered. Fallback to keyword search.
        if len(jobs) == 0 and len(prompt_links) > 0:
            raise ValueError("LLM returned 0 jobs despite having relevant prompt links")
            
        return jobs
    except Exception as e:
        logger.warning(f"LLM extraction failed or returned 0 jobs for {cfg.company}: {e}. Falling back to keyword search.")
        fallback = []
        fallback_kws = [k.lower() for k in keywords] if keywords else ["engineer", "developer", "scientist", "quant", "analyst"]
        for link in links:
            if any(k in link["title"].lower() for k in fallback_kws):
                fallback.append({
                    "title": link["title"],
                    "url": link["url"],
                    "snippet": "Discovered via fallback keyword search.",
                    "company": cfg.company,
                    "location": "",
                    "source": "career_portal"
                })
        return fallback



async def _scrape_with_playwright(cfg: CareerPageConfig, keywords: List[str], target_location: str, max_jobs: int, get_browser_context) -> List[dict]:

    # To be extremely efficient and respect the page's location/search filters,
    # if the config uses a location filter (like auto_search or india_url) or pagination,
    # we run a single search with an empty keyword. This utilizes the portal's built-in location filter (e.g. Bengaluru) to load all jobs.
    use_location_only = (
        cfg.regional_url is not None or 
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
                await _execute_navigation(page, cfg, "", target_location)

                # Extract initial page
                html = await page.content()
                all_jobs.extend(await _extract_jobs_with_llm(html, page.url, cfg, keywords))

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
                                new_jobs = await _extract_jobs_with_llm(html, page.url, cfg, keywords)
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
                await _execute_navigation(page, cfg, keyword, target_location)
                html = await page.content()
                all_jobs.extend(await _extract_jobs_with_llm(html, page.url, cfg, keywords))

                # Try additional keyword searches on same portal
                # Run up to 2 additional searches but avoid long sequential waits
                for kw in keywords[1:3]:
                    await _execute_navigation(page, cfg, kw, target_location)
                    html = await page.content()
                    all_jobs.extend(await _extract_jobs_with_llm(html, page.url, cfg, keywords))
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
                        all_jobs.extend(await _extract_jobs_with_llm(html, page.url, cfg, keywords))
                    else:
                        keyword = keywords[0] if keywords else "data scientist"
                        await _execute_navigation(page, cfg, keyword)
                        html = await page.content()
                        all_jobs.extend(await _extract_jobs_with_llm(html, page.url, cfg, keywords))
                        for kw in keywords[1:3]:
                            await _execute_navigation(page, cfg, kw)
                            html = await page.content()
                            all_jobs.extend(await _extract_jobs_with_llm(html, page.url, cfg, keywords))
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
    target_location: str = "",
    max_jobs: int = 15,
    get_browser_context=None,
) -> dict:
    """
    Scrape a company's hardcoded career portal.
    Returns {company, career_url, portal_type, navigation_instructions, jobs: [...]}
    """
    cfg = get_career_config(company)
    
    # Fallback and overriding: check if we have a user-defined URL mapping in config.json
    import json
    import os
    user_url = None
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                app_config = json.load(f)
                user_url = app_config.get("company_career_pages", {}).get(company)
        except Exception:
            pass
            
    if not cfg:
        if not user_url:
            return {
                "company": company,
                "error": f"No hardcoded career page and no user URL mapping in config.json for '{company}'.",
                "jobs": [],
            }
            
        # Dynamically determine portal type
        portal_type = "custom"
        ats_slug = None
        
        # Check for greenhouse / lever / rippling in URL
        if "greenhouse.io" in user_url:
            portal_type = "greenhouse"
            match = re.search(r'greenhouse\.io/([^/?#\s]+)', user_url)
            if match:
                ats_slug = match.group(1)
        elif "lever.co" in user_url:
            portal_type = "lever"
            match = re.search(r'lever\.co/([^/?#\s]+)', user_url)
            if match:
                ats_slug = match.group(1)
        elif "rippling.com" in user_url:
            portal_type = "rippling"
            match = re.search(r'rippling\.com/([^/?#\s]+)', user_url)
            if match:
                ats_slug = match.group(1)
        elif "workday" in user_url or "myworkdayjobs.com" in user_url:
            portal_type = "workday"
            
        cfg = CareerPageConfig(
            company=company,
            career_url=user_url,
            regional_url=user_url,
            portal_type=portal_type,
            ats_slug=ats_slug,
            navigation_steps=[
                {"action": "goto", "url": "{career_url}"},
                {"action": "wait", "ms": 4000},
                {"action": "auto_search"},
                {"action": "wait", "ms": 3000},
                {"action": "scroll", "times": 5, "pause_ms": 600},
            ],
            model_instructions=f"Dynamic generic crawling for {company} based on user URL."
        )
    else:
        # If config exists in registry, OVERRIDE its URL with the user's config.json URL to prevent hardcoding
        if user_url:
            cfg.career_url = user_url
            cfg.regional_url = user_url
            # Also update navigation steps that use literal URLs
            for step in cfg.navigation_steps:
                if step.get("url") and "http" in step["url"]:
                    step["url"] = user_url

    keywords = role_keywords or ROLE_KEYWORDS_DEFAULT
    jobs: List[dict] = []

    # Fast path: known ATS APIs
    if cfg.portal_type == "lever" and cfg.ats_slug:
        jobs = _scrape_lever(cfg, keywords, target_location, max_jobs)
    elif cfg.portal_type == "greenhouse" and cfg.ats_slug:
        jobs = _scrape_greenhouse(cfg, keywords, target_location, max_jobs)
    elif cfg.portal_type == "rippling" and cfg.ats_slug:
        jobs = _scrape_rippling(cfg, keywords, target_location, max_jobs)
    elif cfg.portal_type == "custom_uber":
        # Uber Freight posts on Greenhouse — supplement main portal
        freight_cfg = CareerPageConfig(
            company=cfg.company,
            career_url=cfg.career_url,
            portal_type="greenhouse",
            ats_slug="uberfreight",
        )
        jobs = _scrape_greenhouse(freight_cfg, keywords, target_location, max_jobs)

    # Browser path for custom/workday/google/etc.
    if len(jobs) < max_jobs and get_browser_context is not None:
        try:
            browser_jobs = await _scrape_with_playwright(cfg, keywords, target_location, max_jobs - len(jobs), get_browser_context)
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
