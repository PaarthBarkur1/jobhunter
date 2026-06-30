import asyncio
import logging
import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime

from core.database import get_db_session
from core.models import ScanLog, JobPosting, Company
from services.scraper_service import ScraperService
from services.llm_service import LLMService
from services.evaluator_service import EvaluatorService
from career_pages import get_career_config, CAREER_PAGE_REGISTRY

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

logger = logging.getLogger(__name__)

class Orchestrator:
    def __init__(self, resume_path: str, preferences: Dict[str, Any]):
        self.resume_path = resume_path
        self.preferences = preferences
        self.scraper_service = ScraperService()
        self.llm_service = LLMService()
        self.evaluator_service = EvaluatorService(self.llm_service)
        self.resume_text = ""

    async def _load_resume(self):
        try:
            with open(self.resume_path, 'r', encoding='utf-8') as f:
                self.resume_text = f.read()
        except Exception as e:
            logger.error(f"Failed to load resume from {self.resume_path}: {e}")
            self.resume_text = "Experienced Software Engineer" # Fallback if missing
            
    async def _get_target_companies(self, session) -> List[Company]:
        # First, sync companies from the config into the database
        target_names = self.preferences.get("target_companies", [])
        career_pages = self.preferences.get("company_career_pages", {})
        
        # Reset all current is_target flags to false to mirror config exact state
        stmt = select(Company)
        result = await session.execute(stmt)
        for c in result.scalars().all():
            c.is_target = False
            
        # Add or update targets based on config
        for name in target_names:
            stmt = select(Company).where(Company.name == name)
            existing = await session.execute(stmt)
            company = existing.scalar_one_or_none()
            
            # Fix 1: The Configuration Mapping Gap
            career_cfg = get_career_config(name)
            ats_provider = career_cfg.portal_type if career_cfg else None
            ats_slug = career_cfg.ats_slug if career_cfg else None
            url = career_pages.get(name) or (career_cfg.regional_url if career_cfg else None) or (career_cfg.career_url if career_cfg else None)
            
            if not company:
                company = Company(name=name, career_url=url, ats_provider=ats_provider, ats_slug=ats_slug, is_target=True)
                session.add(company)
            else:
                company.is_target = True
                company.career_url = url or company.career_url
                company.ats_provider = ats_provider or company.ats_provider
                company.ats_slug = ats_slug or company.ats_slug
                
        await session.commit()
        
        stmt = select(Company).where(Company.is_target == True)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def run_agent_pipeline(self):
        """
        Main execution workflow (DAG) for the multi-agent system.
        Strictly delegates to specialized services.
        """
        # Step A: Initialization
        await self._load_resume()
        await self.llm_service.start()
        
        async with get_db_session() as session:
            # Create a new ScanLog entry
            scan_log = ScanLog(status="running", jobs_discovered=0)
            session.add(scan_log)
            await session.commit()
            await session.refresh(scan_log)
            
            try:
                companies = await self._get_target_companies(session)
                if not companies:
                    logger.warning("No target companies found in the database. Please add targets before running.")
                    
                # Fix 3: Stale Job Accumulation
                try:
                    logger.info("Verifying stale jobs...")
                    stmt = select(JobPosting).where(JobPosting.status == 'unrated')
                    unrated_jobs = (await session.execute(stmt)).scalars().all()
                    
                    async def ping_url(job: JobPosting):
                        try:
                            async with aiohttp.ClientSession() as http_session:
                                async with http_session.get(job.url, timeout=10) as response:
                                    if response.status == 404:
                                        return job
                        except Exception:
                            pass
                        return None
                            
                    ping_tasks = [ping_url(j) for j in unrated_jobs]
                    if ping_tasks:
                        dead_jobs = await asyncio.gather(*ping_tasks)
                        dead_jobs = [j for j in dead_jobs if j is not None]
                        for dj in dead_jobs:
                            dj.status = 'closed'
                        await session.commit()
                        logger.info(f"Pruned {len(dead_jobs)} stale jobs.")
                except Exception as e:
                    logger.error(f"Error verifying stale jobs: {e}")
                    
                # Step B: Discovery (Concurrency: 5 via Semaphore)
                semaphore = asyncio.Semaphore(5)
                all_found_links = []
                
                async def fetch_company_links(company: Company):
                    if not company.career_url:
                        return
                    async with semaphore:
                        try:
                            logger.info(f"Scanning {company.name} at {company.career_url}")
                            result = await self.scraper_service.scrape_career_page(company.career_url)
                            # Handle fallback links or api scraped links
                            links = result.get("dom_links", [])
                            for link in links:
                                all_found_links.append((company, link))
                        except Exception as e:
                            logger.error(f"Error discovering links for {company.name}: {e}")

                tasks = [fetch_company_links(company) for company in companies]
                if tasks:
                    await asyncio.gather(*tasks)
                
                # Step C: Database Deduplication
                new_urls_to_process = []
                for company, link in all_found_links:
                    stmt = select(JobPosting).where(JobPosting.url == link)
                    existing = await session.execute(stmt)
                    if not existing.scalar_one_or_none():
                        new_urls_to_process.append((company, link))
                        
                logger.info(f"Found {len(new_urls_to_process)} new job URLs out of {len(all_found_links)} total.")
                
                # Step D: Extraction & Evaluation
                for company, url in new_urls_to_process:
                    try:
                        # Fetch raw description
                        raw_text = await self.scraper_service.extract_job_description(url)
                        if not raw_text:
                            logger.warning(f"No text extracted for {url}. Skipping.")
                            continue
                            
                        # Evaluate against resume
                        eval_result = await self.evaluator_service.evaluate_job(
                            job_text=raw_text, 
                            user_resume=self.resume_text
                        )
                        
                        # Step E: Persistence (Fix 2: The Unique Constraint Race Condition)
                        stmt = insert(JobPosting).values(
                            url=url,
                            title="Discovered Job Role",
                            company_id=company.id,
                            raw_description=raw_text,
                            match_score=eval_result.get("match_score", 0),
                            match_reason=eval_result.get("match_reason"),
                            required_skills=eval_result.get("required_skills", []),
                            is_curve_ball=eval_result.get("is_curve_ball", False),
                            curve_ball_reason=eval_result.get("curve_ball_reason"),
                            status="unrated"
                        )
                        stmt = stmt.on_conflict_do_nothing(index_elements=['url'])
                        await session.execute(stmt)
                        await session.commit()
                        scan_log.jobs_discovered += 1
                        
                    except Exception as e:
                        # Phase 4 Resilience: One failed job must not crash the entire pipeline
                        logger.error(f"Failed processing job URL {url}: {e}")
                        await session.rollback()
                        continue
                
                # Step F: Cleanup & Finalization
                scan_log.status = "completed"
                await session.commit()
                
            except Exception as e:
                logger.error(f"Pipeline crashed: {e}")
                scan_log.status = "failed"
                scan_log.error_message = str(e)
                await session.commit()
            finally:
                # Phase 4 Constraints: Session Management and proper teardown
                await self.scraper_service.cleanup()
                await self.llm_service.stop()

# Helper function to expose the run method easily for cron jobs / CLI
async def run_pipeline(resume_path: str, preferences: Dict[str, Any]):
    orchestrator = Orchestrator(resume_path, preferences)
    await orchestrator.run_agent_pipeline()
