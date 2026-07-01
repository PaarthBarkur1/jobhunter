import asyncio
import json
import logging
import random
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, Response
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ScraperService:
    def __init__(self):
        self.playwright = None
        self.browser = None
    
    async def initialize(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            logger.info("Playwright initialized.")

    async def cleanup(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Playwright cleanup complete.")

    async def fetch_urls_from_page(self, page: Page, base_url: str) -> List[Dict[str, str]]:
        """
        Fallback method using BeautifulSoup to extract /job/ links from DOM.
        Does NOT use LLMs to find links.
        """
        import urllib.parse
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        job_links = {}
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            title = a_tag.get_text(strip=True)
            
            # Fix 3: Broken SPA URLs
            abs_url = urllib.parse.urljoin(base_url, href)
            abs_lower = abs_url.lower()
            
            # Filter out generic base URLs
            if abs_url.rstrip('/') == base_url.rstrip('/') or href in ['/', '#']:
                continue
                
            # Filter out obvious non-job links
            if any(skip in abs_lower for skip in ['/login', '/signin', '/signup', '/about', 'mailto:']):
                continue
                
            is_job = False
            
            # 1. Contains standard job path segments or query params
            if any(x in abs_lower for x in ['/job/', '/role/', '/opening/', '/req/', 'jobid=', 'reqid=', 'requisition']):
                is_job = True
            
            # 2. Contains UUID-like pattern (e.g., Lever)
            elif re.search(r'/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}', abs_lower):
                is_job = True
                
            # 3. Path ends with a string containing digits (very common for job IDs)
            elif re.search(r'/[a-zA-Z0-9-]*\d+[a-zA-Z0-9-]*$', urllib.parse.urlparse(abs_url).path):
                path_segments = urllib.parse.urlparse(abs_url).path.strip('/').split('/')
                if len(path_segments) >= 2:
                    is_job = True

            if is_job:
                if abs_url not in job_links or not job_links[abs_url]:
                    job_links[abs_url] = title
                
        return [{"url": u, "title": t} for u, t in job_links.items()]

    async def scrape_career_page(self, url: str) -> Dict[str, Any]:
        """
        Navigates to the career page and attempts to intercept API responses.
        Falls back to DOM scraping if API interception yields nothing.
        """
        if not self.browser:
            await self.initialize()

        context = await self.browser.new_context()
        page = await context.new_page()
        
        api_results: List[Dict] = []
        
        async def handle_response(response: Response):
            if response.request.resource_type in ["xhr", "fetch"]:
                try:
                    res_url = response.url.lower()
                    if "workday" in res_url or "eightfold" in res_url or "jobs" in res_url:
                        json_data = await response.json()
                        api_results.append(json_data)
                except Exception:
                    pass

        page.on("response", handle_response)
        
        result = {"url": url, "api_data": [], "dom_links": []}
        
        try:
            # Fix 5: The IP Ban Risk (Introduce random jitter)
            await asyncio.sleep(random.uniform(1.0, 3.5))
            try:
                # Use domcontentloaded instead of networkidle to prevent 30s timeouts on analytics-heavy sites
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(3) # Let JS frameworks hydrate
            except Exception as e:
                logger.warning(f"Timeout reaching {url}, proceeding to extract from loaded DOM anyway: {e}")
            
            if api_results:
                result["api_data"] = api_results
            
            # Always fallback to extracting DOM links just in case API data is unhandled
            result["dom_links"] = await self.fetch_urls_from_page(page, url)
                
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
        finally:
            await context.close()
            
        return result
        
    async def extract_job_description(self, url: str) -> str:
        """
        Extracts raw, cleaned text from a job posting URL.
        No LLMs are used for DOM parsing.
        """
        if not self.browser:
            await self.initialize()
            
        context = await self.browser.new_context()
        page = await context.new_page()
        text_content = ""
        
        try:
            # Fix 5: The IP Ban Risk (Introduce random jitter)
            await asyncio.sleep(random.uniform(1.0, 3.5))
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                logger.warning(f"Timeout reaching {url}, proceeding to extract from loaded DOM anyway: {e}")
            
            # Hard Jitter for SPAs to render DOM after domcontentloaded
            await asyncio.sleep(2)
            
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove scripts, styles, nav, footer, header to get clean text
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.extract()
                
            # Attempt extraction using standard ATS selectors
            ats_selectors = ["main", ".job-description", "article"]
            for selector in ats_selectors:
                element = soup.select_one(selector)
                if element:
                    text_content = element.get_text(separator=' ', strip=True)
                    if text_content:
                        break
            
            # Fallback to evaluating document.body.innerText if selectors yield no text
            if not text_content:
                text_content = await page.evaluate("document.body.innerText")
            
            # Clean text: strip excessive whitespace and newlines
            if text_content:
                text_content = re.sub(r'\s+', ' ', text_content).strip()
            
        except Exception as e:
            logger.error(f"Error extracting job description from {url}: {e}")
        finally:
            await context.close()
            
        return text_content
