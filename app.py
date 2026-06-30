import os
import json
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        from uvicorn.loops import asyncio as uvicorn_asyncio
        uvicorn_asyncio.asyncio_setup = lambda: None
    except ImportError:
        pass

import logging
import subprocess
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import List
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from core.database import get_db_session
from core.models import JobPosting, Company, ScanLog
from workers.orchestrator import run_pipeline

# Import preference update from job_agent
from job_agent import update_preferences_profile

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("job_hunter_web")

app = FastAPI(title="Job Hunter Dashboard API")

# Global tracking for background scan process
scan_task = None
scheduler_process = None
ollama_process = None
scan_lock = asyncio.Lock()
scheduler_lock = asyncio.Lock()
preferences_lock = asyncio.Lock()

async def safe_update_preferences(*args, **kwargs):
    async with preferences_lock:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: update_preferences_profile(*args, **kwargs))

import socket

def is_ollama_running(host='127.0.0.1', port=11434) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0

@app.on_event("startup")
async def startup_event():
    global ollama_process
    if not is_ollama_running():
        logger.info("Ollama server not detected on port 11434. Starting 'ollama serve' in background with GPU optimizations...")
        env = os.environ.copy()
        # Prevent the model from being aggressively unloaded to save VRAM swapping/crashes
        env["OLLAMA_KEEP_ALIVE"] = "24h"
        # Ensure CUDA is enabled (we don't disable it since user wants GPU efficiency)
        if "CUDA_VISIBLE_DEVICES" in env and env["CUDA_VISIBLE_DEVICES"] == "":
            del env["CUDA_VISIBLE_DEVICES"]
            
        try:
            ollama_process = subprocess.Popen(
                ["ollama", "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # On Windows, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP prevents Ctrl+C from killing it abruptly before shutdown hook
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            logger.info("Successfully launched Ollama server.")
        except Exception as e:
            logger.error(f"Failed to launch Ollama server: {e}")
    else:
        logger.info("Detected existing Ollama server running.")

@app.on_event("shutdown")
async def shutdown_event():
    global ollama_process
    if ollama_process:
        logger.info("Shutting down background Ollama server...")
        try:
            ollama_process.terminate()
            ollama_process.wait(timeout=5)
        except Exception as e:
            logger.error(f"Error terminating Ollama: {e}")

# Pydantic request models
class FeedbackRequest(BaseModel):
    date: str
    job_id: str
    status: str  # "thumbs_up" or "thumbs_down"
    comment: str

# Helper to read preferences file
def get_preferences_content() -> str:
    pref_path = ".resumes/preferences.md"
    if os.path.exists(pref_path):
        try:
            with open(pref_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading preferences: {e}")
    return "No preferences set yet. Rate jobs on the dashboard to build your profile."

DEFAULT_CONFIG = {
    "ollama_model": "deepseek-r1:1.5b",
    "target_compensation_threshold": 100000,
    "currency": "USD",
    "target_location": "Remote",
    "disliked_companies": ["infosys", "wipro", "tcs", "cognizant"],
    "resumes_dir": ".resumes",
    "search_queries": [
        "data scientist",
        "applied scientist",
        "quant analyst",
        "site:linkedin.com/jobs/view \"quant researcher\"",
        "site:linkedin.com/jobs/view \"data scientist\"",
        "site:linkedin.com/jobs/view \"applied researcher\"",
        "site:indeed.com/viewjob \"quant researcher\"",
        "site:indeed.com/viewjob \"data scientist\"",
        "site:indeed.com/viewjob \"applied researcher\"",
        "site:boards.greenhouse.io python",
        "site:lever.co quant researcher",
        "site:reddit.com/r/cscareerquestions \"hiring\" OR \"who is hiring\"",
        "site:reddit.com/r/quant \"hiring\" OR \"recruiters\""
    ],
    "headless": True,
    "user_data_dir": ".browser_profile",
    "preferences_path": ".resumes/preferences.md",
    "target_companies": [
        "Millennium Management",
        "Tower Research Capital",
        "Jane Street",
        "D. E. Shaw",
        "Google",
        "Uber",
        "AQR Capital Management",
        "J P Morgan",
        "Goldman Sachs",
        "Microsoft",
        "Morgan Stanley",
        "AMD",
        "Nvidia",
        "Meesho",
        "Rippling",
        "QRT",
        "BCG X",
        "IMC Trading"
    ],
    "direct_job_urls": [],
    "jobs_digest_path": "jobs_digest.md",
    "restrict_to_target_companies": False,
    "max_additional_companies": 30,
    "max_jobs_to_process": 25,
    "company_career_pages": {},
    "scan_interval_hours": 12,
    "career_scrape_max_per_company": 15
}

# Helper to load config
def load_config() -> dict:
    config_path = "config.json"
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    config = json.loads(content)
        except Exception as e:
            logger.error(f"Error reading or parsing config.json: {e}")
            config = {}
            
    # Check if critical lists/keys are missing
    modified = False
    for k, v in DEFAULT_CONFIG.items():
        if k not in config:
            config[k] = v
            modified = True
            
    if modified:
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            logger.info("config.json was missing or empty keys. Restored defaults successfully.")
        except Exception as e:
            logger.error(f"Failed to save default config.json: {e}")
            
    return config

# --- API ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serve the dashboard UI."""
    template_path = os.path.join("templates", "index.html")
    if os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    else:
        raise HTTPException(status_code=404, detail="Dashboard UI template not found.")

@app.get("/api/dates")
async def get_available_dates():
    """Retrieve all unique daily dates from the SQLite DB."""
    async with get_db_session() as session:
        stmt = select(JobPosting.date_discovered)
        result = await session.execute(stmt)
        dates_set = {d.strftime("%Y-%m-%d") for d in result.scalars().all() if d}
        dates = list(dates_set)
        dates.sort(reverse=True)
        return dates

@app.get("/api/jobs")
async def get_jobs_for_date(date: str):
    """Retrieve jobs and current preferences profile from SQLite."""
    jobs = []
    summary = ""
    
    async with get_db_session() as session:
        if date == "all":
            stmt = select(JobPosting).options(selectinload(JobPosting.company)).where(JobPosting.status != 'closed').order_by(desc(JobPosting.match_score))
            result = await session.execute(stmt)
            job_postings = result.scalars().all()
            summary = "### Combined Job Search History\nShowing all persistent, verified open job postings discovered across all previous scans."
        else:
            stmt = select(JobPosting).options(selectinload(JobPosting.company)).order_by(desc(JobPosting.match_score))
            result = await session.execute(stmt)
            all_jobs = result.scalars().all()
            job_postings = [j for j in all_jobs if j.date_discovered and j.date_discovered.strftime("%Y-%m-%d") == date]
            
        for jp in job_postings:
            jobs.append({
                "id": str(jp.id),
                "url": jp.url,
                "title": jp.title,
                "company": jp.company.name if jp.company else "Unknown",
                "role_category": jp.role_category,
                "location": jp.location,
                "source": jp.source,
                "estimated_ctc": jp.estimated_ctc,
                "explicit_salary_str": jp.explicit_salary_str,
                "experience_level": jp.experience_level,
                "required_skills": jp.required_skills,
                "match_score": jp.match_score,
                "match_reason": jp.match_reason,
                "is_curve_ball": jp.is_curve_ball,
                "curve_ball_reason": jp.curve_ball_reason,
                "status": jp.status,
                "feedback_comment": jp.feedback_comment,
                "posted_date": jp.posted_date,
                "date_discovered": jp.date_discovered.isoformat() if jp.date_discovered else ""
            })
                
    return {
        "date": date,
        "jobs": jobs,
        "summary": summary,
        "preferences": get_preferences_content()
    }

@app.get("/api/trends")
async def get_trends():
    """Aggregate trend statistics from the SQLite database."""
    total_jobs = 0
    curve_balls = 0
    high_matches = 0
    role_counts = {}
    company_counts = {}
    
    async with get_db_session() as session:
        stmt = select(func.count()).select_from(JobPosting)
        total_jobs = await session.scalar(stmt)
        
        stmt = select(func.count()).select_from(JobPosting).where(JobPosting.is_curve_ball == True)
        curve_balls = await session.scalar(stmt)
        
        stmt = select(func.count()).select_from(JobPosting).where(JobPosting.match_score >= 80)
        high_matches = await session.scalar(stmt)
        
        stmt = select(JobPosting).options(selectinload(JobPosting.company))
        result = await session.execute(stmt)
        all_jobs = result.scalars().all()
        
        for job in all_jobs:
            title = job.title.strip() if job.title else "Unknown Role"
            role_counts[title] = role_counts.get(title, 0) + 1
            
            company = job.company.name.strip() if job.company else "Unknown Company"
            company_counts[company] = company_counts.get(company, 0) + 1
            
    sorted_roles = [{"role": k, "count": v} for k, v in sorted(role_counts.items(), key=lambda x: x[1], reverse=True)]
    sorted_companies = [{"company": k, "count": v} for k, v in sorted(company_counts.items(), key=lambda x: x[1], reverse=True)]
    
    return {
        "total_jobs_scanned": total_jobs,
        "strong_matches": high_matches,
        "curve_balls": curve_balls,
        "top_roles": sorted_roles[:5],
        "top_companies": sorted_companies[:5]
    }

@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest, background_tasks: BackgroundTasks):
    """Submit rating and comment for a job posting, and asynchronously update preferences profile."""
    config = load_config()
    model_name = config.get("ollama_model", "deepseek-r1:1.5b")
    
    async with get_db_session() as session:
        stmt = select(JobPosting).options(selectinload(JobPosting.company)).where(JobPosting.id == int(req.job_id))
        result = await session.execute(stmt)
        job_found = result.scalar_one_or_none()
        
        if not job_found:
            raise HTTPException(status_code=404, detail="Job ID not found in database.")
            
        job_found.status = req.status
        job_found.feedback_comment = req.comment
        await session.commit()
        
        co_name = job_found.company.name if job_found.company else "Unknown"
        
        if req.status == "thumbs_up":
            t_cos = config.get("target_companies", [])
            if co_name and co_name != "N/A" and co_name not in t_cos and co_name != "Unknown":
                t_cos.append(co_name)
                config["target_companies"] = t_cos
                
                career_pages = config.get("company_career_pages", {})
                job_url = job_found.url
                if job_url and ("greenhouse.io" in job_url or "lever.co" in job_url) and co_name not in career_pages:
                    career_pages[co_name] = job_url
                    config["company_career_pages"] = career_pages
                    
                try:
                    with open("config.json", "w", encoding="utf-8") as cf:
                        json.dump(config, cf, indent=2)
                    logger.info(f"Promoted company '{co_name}' to target list.")
                except Exception as e:
                    logger.error(f"Failed to save config.json on company promotion: {e}")

        # Fix 4: File I/O Race Conditions on preferences.md (Use safe wrapper)
        background_tasks.add_task(
            safe_update_preferences,
            job_found.title,
            co_name,
            req.status,
            req.comment,
            config.get("preferences_path", ".resumes/preferences.md"),
            model_name
        )
        
    return {"status": "success", "message": "Feedback recorded, preference profile update scheduled."}

@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    """Spawns the orchestrator DAG workflow in the background."""
    global scan_task
    async with scan_lock:
        async with get_db_session() as session:
            stmt = select(ScanLog).order_by(desc(ScanLog.run_time)).limit(1)
            result = await session.execute(stmt)
            latest_scan = result.scalar_one_or_none()
            if latest_scan and latest_scan.status == "running":
                return {"status": "running", "message": "Scan already in progress."}
                
        config = load_config()
        resume_path = config.get("preferences_path", ".resumes/preferences.md")
        
        logger.info("Spawning background orchestrator pipeline...")
        scan_task = asyncio.create_task(run_pipeline(resume_path=resume_path, preferences=config))
        return {"status": "started", "message": "Job agent scan started in background."}

@app.get("/api/scan/status")
async def get_scan_status():
    """Query the ScanLog table and return the most recent entry."""
    async with get_db_session() as session:
        stmt = select(ScanLog).order_by(desc(ScanLog.run_time)).limit(1)
        result = await session.execute(stmt)
        latest_scan = result.scalar_one_or_none()
        
        if not latest_scan:
            return {"status": "idle", "jobs_discovered": 0}
            
        return {
            "status": latest_scan.status,
            "jobs_discovered": latest_scan.jobs_discovered,
            "error_message": latest_scan.error_message
        }

class CompaniesRequest(BaseModel):
    companies: List[str]

@app.get("/api/master_companies")
async def get_master_companies():
    db_path = "data/companies_db.json"
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                return {"companies": json.load(f)}
        except Exception as e:
            logger.error(f"Failed to read master companies DB: {e}")
    return {"companies": []}

@app.get("/api/companies")
async def get_active_companies():
    config = load_config()
    return config.get("target_companies", [])

@app.post("/api/companies")
async def save_companies(req: CompaniesRequest):
    """Save the updated list of target companies back to config.json."""
    config_path = "config.json"
    config = load_config()
    config["target_companies"] = req.companies
    
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return {"status": "success", "companies": config["target_companies"]}
    except Exception as e:
        logger.error(f"Failed to write config.json: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save target companies: {e}")

class CareerPageMappingRequest(BaseModel):
    company: str
    url: str

@app.get("/api/career-pages")
async def get_career_pages():
    """Retrieve the mapping of company names to their career page URLs."""
    config = load_config()
    return config.get("company_career_pages", {})

@app.post("/api/career-pages")
async def save_career_page_mapping(req: CareerPageMappingRequest):
    """Save a new or updated company name to career page URL mapping."""
    config_path = "config.json"
    config = load_config()
    
    career_pages = config.get("company_career_pages", {})
    co_name = req.company.strip()
    co_url = req.url.strip()
    
    if not co_name or not co_url:
        raise HTTPException(status_code=400, detail="Company name and URL cannot be empty.")
        
    career_pages[co_name] = co_url
    config["company_career_pages"] = career_pages
    
    # Also automatically promote to target_companies if not present
    target_cos = config.get("target_companies", [])
    if co_name not in target_cos:
        target_cos.append(co_name)
        config["target_companies"] = target_cos
        
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return {
            "status": "success", 
            "company": co_name, 
            "url": co_url, 
            "target_companies": config["target_companies"]
        }
    except Exception as e:
        logger.error(f"Failed to save career page mapping: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save mapping: {e}")

class QueriesRequest(BaseModel):
    queries: List[str]

@app.get("/api/queries")
async def get_queries():
    """Retrieve the list of search queries/roles from config.json."""
    config = load_config()
    return config.get("search_queries", [])

@app.post("/api/queries")
async def save_queries(req: QueriesRequest):
    """Save the updated list of search queries/roles back to config.json."""
    config_path = "config.json"
    config = load_config()
    config["search_queries"] = req.queries
    
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return {"status": "success", "queries": config["search_queries"]}
    except Exception as e:
        logger.error(f"Failed to write config.json: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save search queries: {e}")

class RestrictToggleRequest(BaseModel):
    restrict: bool

@app.get("/api/config")
async def get_app_config():
    """Retrieve config settings."""
    config = load_config()
    return {
        "restrict_to_target_companies": config.get("restrict_to_target_companies", False),
        "scan_interval_hours": config.get("scan_interval_hours", 12),
        "career_scrape_max_per_company": config.get("career_scrape_max_per_company", 15),
    }

@app.get("/api/career-pages")
async def get_career_pages():
    """Return hardcoded career portal URLs for target companies."""
    from career_pages import get_career_url_map, CAREER_PAGE_REGISTRY
    config = load_config()
    return {
        "target_companies": config.get("target_companies", []),
        "career_pages": get_career_url_map(),
        "portals": {
            cfg.company: {
                "url": cfg.india_url or cfg.career_url,
                "portal_type": cfg.portal_type,
                "navigation_instructions": cfg.model_instructions.strip(),
            }
            for cfg in CAREER_PAGE_REGISTRY.values()
        },
    }

@app.post("/api/scheduler/start")
async def start_scheduler():
    """Start the background scheduler that runs career page scans on an interval."""
    global scheduler_process
    async with scheduler_lock:
        if scheduler_process and scheduler_process.poll() is None:
            return {"status": "running", "message": "Scheduler already running."}
        python_exe = os.path.join(".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = "python"
        try:
            config = load_config()
            interval = config.get("scan_interval_hours", 12)
            logger.info(f"Starting scheduler (every {interval}h)...")
            scheduler_process = subprocess.Popen([python_exe, "scheduler.py"])
            return {
                "status": "started",
                "message": f"Scheduler started. Scans every {interval} hours.",
                "scan_interval_hours": interval,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {e}")

@app.post("/api/scheduler/stop")
async def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler_process
    async with scheduler_lock:
        if not scheduler_process or scheduler_process.poll() is not None:
            scheduler_process = None
            return {"status": "idle", "message": "Scheduler is not running."}
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(scheduler_process.pid)], capture_output=True)
            scheduler_process = None
            return {"status": "stopped", "message": "Scheduler stopped."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to stop scheduler: {e}")

@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """Check if the periodic scheduler is running."""
    global scheduler_process
    config = load_config()
    if scheduler_process is None:
        return {"status": "idle", "scan_interval_hours": config.get("scan_interval_hours", 12)}
    poll_res = scheduler_process.poll()
    if poll_res is None:
        return {"status": "running", "scan_interval_hours": config.get("scan_interval_hours", 12)}
    return {"status": "stopped", "exit_code": poll_res, "scan_interval_hours": config.get("scan_interval_hours", 12)}

@app.post("/api/config/toggle-restrict")
async def toggle_restrict(req: RestrictToggleRequest):
    """Save the toggle state of target company restriction to config.json."""
    config_path = "config.json"
    config = load_config()
    config["restrict_to_target_companies"] = req.restrict
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return {"status": "success", "restrict_to_target_companies": config["restrict_to_target_companies"]}
    except Exception as e:
        logger.error(f"Failed to write config.json on toggle: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to toggle restriction: {e}")

@app.post("/api/scan/kill")
async def kill_scan():
    """Kill the active async background scan task."""
    global scan_task
    async with scan_lock:
        if scan_task and not scan_task.done():
            scan_task.cancel()
            scan_task = None
            
            # Mark as failed in DB
            async with get_db_session() as session:
                stmt = select(ScanLog).order_by(desc(ScanLog.run_time)).limit(1)
                result = await session.execute(stmt)
                latest_scan = result.scalar_one_or_none()
                if latest_scan and latest_scan.status == "running":
                    latest_scan.status = "failed"
                    latest_scan.error_message = "Killed by user."
                    await session.commit()
            return {"status": "killed", "message": "Scan task terminated."}
            
        return {"status": "idle", "message": "No scan is currently running."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
