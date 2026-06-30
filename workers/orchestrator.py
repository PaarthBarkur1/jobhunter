import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from core.database import get_db_session
from core.models import ScanLog, JobPosting, Company
from services.scraper_service import ScraperService
from services.llm_service import LLMService
from services.evaluator_service import EvaluatorService

from sqlalchemy import select

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
                        
                        # Step E: Persistence
                        job_posting = JobPosting(
                            url=url,
                            title="Discovered Job Role", # Extracted from API natively, or LLM fallback
                            company_id=company.id,
                            raw_description=raw_text,
                            match_score=eval_result.get("match_score", 0),
                            match_reason=eval_result.get("match_reason"),
                            required_skills=eval_result.get("required_skills", []),
                            is_curve_ball=eval_result.get("is_curve_ball", False),
                            curve_ball_reason=eval_result.get("curve_ball_reason"),
                            status="unrated"
                        )
                        session.add(job_posting)
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
