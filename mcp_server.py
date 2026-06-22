import os
import re
import glob
import sys
import logging
import json
import urllib.parse
from mcp.server.fastmcp import FastMCP
from bs4 import BeautifulSoup
import http_client
from duckduckgo_search import DDGS
from pypdf import PdfReader

from career_scraper import scrape_company_careers, format_career_scrape_result
from career_pages import get_career_config, resolve_start_url
from pathlib import Path
import hashlib
import time

# Persistent cache for start-page hashes and known jobs
SEEN_CACHE_PATH = Path("scratch/seen_jobs.json")
SEEN_CACHE_TTL = 60 * 60 * 6  # 6 hours
MISS_THRESHOLD = 3  # remove job after this many consecutive misses


def load_seen_cache() -> dict:
    if not SEEN_CACHE_PATH.exists():
        return {}
    try:
        with SEEN_CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen_cache(data: dict) -> None:
    try:
        SEEN_CACHE_PATH.parent.mkdir(exist_ok=True)
        with SEEN_CACHE_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _html_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
import browser_manager

# Configure logging to sys.stderr to avoid polluting stdout (which is used by stdio transport)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("job_hunter_mcp")

# Initialize FastMCP Server
mcp = FastMCP("Job Hunter MCP Server")

# Use browser_manager.get_page to reuse Playwright and limit concurrent pages

@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> str:
    """
    Search the web for a query. Uses Brave Search API if configured, otherwise simulates a real user on Bing Search (primary)
    or Google Search (secondary) using Playwright Chromium to bypass bot blocks.
    Returns a formatted string containing titles, snippets, and URLs of search results.
    """
    logger.info(f"Searching web for: {query}")
    
    # 1. Check if Brave Search API Key is configured
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)
                    api_key = config.get("brave_api_key")
        except Exception as e:
            logger.error(f"Error reading brave_api_key from config.json: {e}")

    if api_key and api_key != "YOUR_API_KEY":
        logger.info("Using Brave Search API...")
        try:
            url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}"
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": api_key
            }
            response = http_client.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            results = response.json().get("web", {}).get("results", [])
            results_str = []
            for i, r in enumerate(results[:max_results], 1):
                title = r.get("title", "No Title")
                href = r.get("url", "")
                snippet = r.get("description", "")
                results_str.append(f"Result {i}:\nTitle: {title}\nURL: {href}\nSnippet: {snippet}\n")
            
            if results_str:
                return "\n".join(results_str)
        except Exception as e:
            logger.error(f"Brave Search API request failed: {e}. Falling back to browser search...")

    # 2. Simulate user on Bing Search using Playwright Chromium (Highly reliable, no CAPTCHA blocks)
    logger.info("Simulating user search on Bing via Playwright Chromium...")
    try:
        async with browser_manager.get_page() as page:
            # Navigate to Bing
            search_url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}"
            await page.goto(search_url, wait_until="load", timeout=20000)
            await page.wait_for_timeout(1500)  # Wait for results to load

            html = await page.content()
            
        soup = BeautifulSoup(html, "html.parser")
        results_str = []
        count = 1
        
        # Parse Bing organic search results (inside 'li' elements with class 'b_algo')
        for li in soup.find_all("li", class_="b_algo"):
            anchor = li.find("a")
            if anchor and anchor.get("href"):
                link = anchor["href"]
                if not link.startswith("http") or "bing.com" in link:
                    continue
                    
                title_h2 = li.find("h2")
                title = title_h2.get_text().strip() if title_h2 else anchor.get_text().strip()
                
                # Snippet is usually in a paragraph tag
                snippet_p = li.find("p")
                snippet = snippet_p.get_text().strip() if snippet_p else ""
                
                results_str.append(f"Result {count}:\nTitle: {title}\nURL: {link}\nSnippet: {snippet}\n")
                count += 1
                if count > max_results:
                    break
                    
        if results_str:
            logger.info(f"Playwright Bing search successfully returned {len(results_str)} results.")
            return "\n".join(results_str)
        else:
            logger.warning("Playwright Bing search parsed 0 results. Trying Google browser search fallback...")
    except Exception as e:
        logger.error(f"Playwright Bing search failed: {e}. Trying Google browser search fallback...")

    # 3. Simulate user on Google Search using Playwright Chromium (Secondary fallback)
    logger.info("Simulating user search on Google via Playwright Chromium...")
    try:
        async with browser_manager.get_page() as page:
            # Navigate to Google Search
            search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            await page.goto(search_url, wait_until="load", timeout=20000)
            await page.wait_for_timeout(1500)  # Let results load

            html = await page.content()
            
        soup = BeautifulSoup(html, "html.parser")
        results_str = []
        count = 1
        
        # Parse Google organic search results
        for h3 in soup.find_all("h3"):
            anchor = h3.find_parent("a")
            if anchor and anchor.get("href"):
                link = anchor["href"]
                if not link.startswith("http") or "google.com" in link:
                    continue
                    
                title = h3.get_text().strip()
                
                # Find snippet
                snippet = ""
                parent = anchor.find_parent("div")
                if parent:
                    # Look up a couple of levels to find the main result container
                    grandparent = parent.find_parent("div")
                    if grandparent:
                        # Try standard snippet classes
                        snippet_div = grandparent.find("div", class_=lambda c: c and any(cls in c for cls in ["VwiC3b", "yXM1m", "MUbBc", "kb0PBd"]))
                        if snippet_div:
                            snippet = snippet_div.get_text().strip()
                        else:
                            # Fallback: look for other text blocks inside the grandparent that are not the title or link
                            for p_tag in grandparent.find_all(["span", "div"]):
                                p_text = p_tag.get_text().strip()
                                if len(p_text) > 40 and title not in p_text and not p_tag.find("a") and not p_tag.find("h3"):
                                    snippet = p_text
                                    break
                
                results_str.append(f"Result {count}:\nTitle: {title}\nURL: {link}\nSnippet: {snippet}\n")
                count += 1
                if count > max_results:
                    break
                    
        if results_str:
            logger.info(f"Playwright Google search successfully returned {len(results_str)} results.")
            return "\n".join(results_str)
        else:
            logger.warning("Playwright Google search parsed 0 results. Trying DuckDuckGo API fallback...")
    except Exception as e:
        logger.error(f"Playwright Google search failed: {e}. Trying DuckDuckGo API fallback...")

    # 4. Fallback to DuckDuckGo search API (Last resort)
    logger.info("Using DuckDuckGo Search Fallback...")
    results_str = []
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            for i, r in enumerate(results, 1):
                title = r.get("title", "No Title")
                href = r.get("href", "")
                body = r.get("body", "")
                results_str.append(f"Result {i}:\nTitle: {title}\nURL: {href}\nSnippet: {body}\n")
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return f"Error during web search: {str(e)}"
    
    if not results_str:
        return "No results found."
    
    return "\n".join(results_str)

@mcp.tool()
async def fetch_web_page(url: str) -> str:
    """
    Fetch the content of a web page using a headless browser (Chromium) to bypass bot blocks and render JS.
    Returns the first 4000 characters of clean text to avoid token limits.
    """
    logger.info(f"Fetching URL via Playwright Chromium: {url}")
    html = ""
    try:
        async with browser_manager.get_page() as page:
            # Go to URL and wait for page to render (networkidle or timeout)
            await page.goto(url, wait_until="load", timeout=20000)
            await page.wait_for_timeout(1500)  # Wait for SPA/React rendering

            html = await page.content()
    except Exception as e:
        logger.error(f"Playwright failed to fetch URL {url}: {e}. Falling back to requests...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        try:
            response = http_client.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            html = response.text
        except Exception as req_e:
            logger.error(f"Requests fallback also failed: {req_e}")
            return f"Error fetching {url}: {str(req_e)}"
    
    # Strip non-content and boilerplate HTML elements to conserve tokens
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "svg"]):
        element.decompose()
        
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned_text = "\n".join(lines)
    
    # Limit response length to save context space
    return cleaned_text[:4000]

@mcp.tool()
async def scrape_company_career_page(
    company: str,
    role_keywords: str = "",
    max_jobs: int = 15,
) -> str:
    """
    Scrape a target company's hardcoded career portal for relevant job listings.
    Uses portal-specific navigation instructions (Lever/Greenhouse/Rippling APIs or Playwright).
    role_keywords: comma-separated role terms (e.g. 'data scientist,quant researcher').
    Returns job titles, URLs, locations, and navigation instructions for the portal.
    """
    keywords = [k.strip() for k in role_keywords.split(",") if k.strip()] if role_keywords else None
    logger.info(f"Scraping career portal for '{company}' with keywords={keywords}")
    # Pre-check: try to avoid expensive Playwright scrape if the start page hasn't changed
    cache = load_seen_cache()
    comp_cache = cache.get(company, {})

    # Resolve start URL
    start_url = None
    cfg = get_career_config(company)
    if cfg:
        start_url = resolve_start_url(cfg)
    else:
        # fallback to config.json mapping
        try:
            if os.path.exists("config.json"):
                with open("config.json", "r", encoding="utf-8") as f:
                    app_conf = json.load(f)
                    start_url = app_conf.get("company_career_pages", {}).get(company)
        except Exception:
            start_url = None

    now = int(time.time())
    try:
        if start_url:
            resp = http_client.get(start_url)
            resp.raise_for_status()
            h = _html_hash(resp.text)
        else:
            h = None
    except Exception:
        h = None

    # If we have a cached last result and the start page hash matches and TTL not expired,
    # return cached result to avoid Playwright run.
    last_checked = comp_cache.get("last_checked", 0)
    last_hash = comp_cache.get("html_hash")
    if last_hash and h and last_hash == h and (now - last_checked) < SEEN_CACHE_TTL and comp_cache.get("last_result"):
        logger.info(f"No change detected for {company}; returning cached jobs.")
        return format_career_scrape_result(comp_cache.get("last_result"))

    # Otherwise perform a fresh scrape and update cache and miss counters
    result = await scrape_company_careers(
        company=company,
        role_keywords=keywords,
        max_jobs=max_jobs,
        get_browser_context=browser_manager.get_page,
    )

    # Update cache
    try:
        new_urls = [j.get("url") for j in result.get("jobs", []) if j.get("url")]
        old_urls = comp_cache.get("urls", [])
        miss_counts = comp_cache.get("miss_counts", {})

        # Increment miss counts for old URLs missing in new run
        for u in old_urls:
            if u not in new_urls:
                miss_counts[u] = miss_counts.get(u, 0) + 1
            else:
                miss_counts[u] = 0

        # Remove URLs that exceeded miss threshold from stored jobs
        removed = [u for u, c in miss_counts.items() if c >= MISS_THRESHOLD]
        if removed:
            # prune jobs from cached last_result if present
            lr = comp_cache.get("last_result") or {}
            jobs = lr.get("jobs", [])
            jobs = [j for j in jobs if j.get("url") not in removed]
            lr["jobs"] = jobs
            comp_cache["last_result"] = lr
            # clear miss_counts for removed
            for u in removed:
                miss_counts.pop(u, None)

        comp_cache.update({
            "html_hash": h,
            "last_checked": now,
            "urls": new_urls,
            "miss_counts": miss_counts,
            "last_result": result,
        })
        cache[company] = comp_cache
        save_seen_cache(cache)
    except Exception as e:
        logger.error(f"Failed to update seen cache for {company}: {e}")

    return format_career_scrape_result(result)


@mcp.tool()
def read_resumes(directory: str = ".resumes") -> str:
    """
    Read all resume files (TXT, PDF, MD) in the specified directory and return their contents combined.
    """
    logger.info(f"Reading resumes from folder: {directory}")
    if not os.path.exists(directory):
        return f"Directory '{directory}' does not exist."
        
    resumes_content = []
    # Find all files in the directory
    files = glob.glob(os.path.join(directory, "*"))
    
    for file_path in files:
        ext = os.path.splitext(file_path)[1].lower()
        filename = os.path.basename(file_path)
        
        try:
            if ext in [".txt", ".md"]:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                resumes_content.append(f"=== Resume File: {filename} ===\n{content}\n")
            elif ext == ".pdf":
                reader = PdfReader(file_path)
                pdf_text = []
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        pdf_text.append(text)
                content = "\n".join(pdf_text)
                resumes_content.append(f"=== Resume File: {filename} ===\n{content}\n")
        except Exception as e:
            logger.error(f"Error reading file {filename}: {e}")
            resumes_content.append(f"Error reading {filename}: {str(e)}\n")
            
    if not resumes_content:
        return f"No readable resume files (TXT, MD, PDF) found in directory '{directory}'."
        
    return "\n".join(resumes_content)

if __name__ == "__main__":
    # Start the server using Stdio transport (JSON-RPC over standard input/output)
    mcp.run(transport="stdio")
