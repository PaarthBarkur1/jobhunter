import asyncio
import json
import logging
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

    async def fetch_urls_from_page(self, page: Page, base_url: str) -> List[str]:
        """
        Fallback method using BeautifulSoup to extract /job/ links from DOM.
        Does NOT use LLMs to find links.
        """
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        job_links = set()
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/job/' in href.lower() or '/careers/' in href.lower() or '/openings/' in href.lower():
                if href.startswith('/'):
                    href = base_url.rstrip('/') + href
                job_links.add(href)
                
        return list(job_links)

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
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            if api_results:
                result["api_data"] = api_results
            else:
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
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove scripts, styles, nav, footer, header to get clean text
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.extract()
                
            text_content = soup.get_text(separator=' ', strip=True)
            
        except Exception as e:
            logger.error(f"Error extracting job description from {url}: {e}")
        finally:
            await context.close()
            
        return text_content
