import sys
import os
import json
import asyncio
import logging
import subprocess
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload

# ---------------------------------------------------------
# NEW ARCHITECTURE IMPORTS (Fixes the NameError)
# ---------------------------------------------------------
from core.database import get_db_session
from core.models import JobPosting, Company, ScanLog
from workers.orchestrator import run_pipeline

# ---------------------------------------------------------
# CRITICAL WINDOWS FIX: Force ProactorEventLoop for Playwright
# ---------------------------------------------------------
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    # Uvicorn internally overrides the policy back to SelectorEventLoop on Windows.
    # We MUST monkey-patch it to prevent it from breaking Playwright subprocesses.
    try:
        from uvicorn.loops import asyncio as uvicorn_asyncio
        uvicorn_asyncio.asyncio_setup = lambda: None
    except ImportError:
        pass

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("job_hunter_web")

# Global tracking for background processes
ollama_process = None

def is_ollama_running(host='127.0.0.1', port=11434) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0

# ---------------------------------------------------------
# MODERN FASTAPI LIFESPAN (Fixes the on_event Deprecation)
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    global ollama_process
    if not is_ollama_running():
        logger.info("Ollama server not detected. Starting 'ollama serve' in background...")
        env = os.environ.copy()
        env["OLLAMA_KEEP_ALIVE"] = "24h"
        if "CUDA_VISIBLE_DEVICES" in env and env["CUDA_VISIBLE_DEVICES"] == "":
            del env["CUDA_VISIBLE_DEVICES"]
            
        try:
            ollama_process = subprocess.Popen(
                ["ollama", "serve"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            logger.info("Successfully launched Ollama server.")
        except Exception as e:
            logger.error(f"Failed to launch Ollama server: {e}")
    else:
        logger.info("Detected existing Ollama server running.")

    # Yield control back to FastAPI to serve requests
    yield
    
    # --- SHUTDOWN LOGIC ---
    if ollama_process:
        logger.info("Shutting down background Ollama server...")
        try:
            ollama_process.terminate()
            ollama_process.wait(timeout=5)
        except Exception as e:
            logger.error(f"Error terminating Ollama: {e}")

# Initialize app with lifespan
app = FastAPI(title="Job Hunter Dashboard API", lifespan=lifespan)

# --- Pydantic Models for Frontend Interaction ---
class FeedbackRequest(BaseModel):
    date: str
    job_id: str
    status: str  # "thumbs_up" or "thumbs_down"
    comment: str

class CompaniesRequest(BaseModel):
    companies: List[str]

class QueriesRequest(BaseModel):
    queries: List[str]

# --- Helper Functions ---
def load_config() -> dict:
    config_path = "config.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def get_preferences_content() -> str:
    pref_path = ".resumes/preferences.md"
    if os.path.exists(pref_path):
        try:
            with open(pref_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return "No preferences set yet. Rate jobs on the dashboard to build your profile."

# --- API ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serve the dashboard UI."""
    template_path = os.path.join("templates", "index.html")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Dashboard UI template not found.")
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/dates")
async def get_available_dates():
    """Retrieve all distinct daily dates from the SQLite database."""
    async with get_db_session() as session:
        # Cast datetime to date strings for frontend dropdown
        stmt = select(func.date(JobPosting.date_discovered)).distinct().order_by(desc(func.date(JobPosting.date_discovered)))
        result = await session.execute(stmt)
        dates = [row[0] for row in result.all() if row[0]]
        return dates

@app.get("/api/jobs")
async def get_jobs_for_date(date: str):
    """Retrieve jobs seamlessly joined with their Company data from SQLite."""
    async with get_db_session() as session:
        stmt = select(JobPosting).options(selectinload(JobPosting.company)).where(JobPosting.status != 'closed').order_by(desc(JobPosting.match_score))
        
        if date != "all":
            stmt = stmt.where(func.date(JobPosting.date_discovered) == date)
            
        result = await session.execute(stmt)
        jobs_data = []
        
        for job in result.scalars():
            jobs_data.append({
                "id": str(job.id),
                "title": job.title,
                "company": job.company.name if job.company else "Unknown",
                "url": job.url,
                "source": job.source,
                "ctc": job.estimated_ctc,
                "required_skills": job.required_skills or [],
                "experience_level": job.experience_level,
                "location": job.location,
                "role": job.role_category,
                "description": job.raw_description,
                "posted_date": job.posted_date,
                "match_score": job.match_score,
                "match_reason": job.match_reason,
                "is_curve_ball": job.is_curve_ball,
                "curve_ball_reason": job.curve_ball_reason,
                "status": job.status,
                "feedback_comment": job.feedback_comment
            })
            
        return {
            "date": date,
            "jobs": jobs_data,
            "summary": "### Job Search History\nShowing persistent database records.",
            "preferences": get_preferences_content()
        }

@app.get("/api/trends")
async def get_trends():
    """Aggregate trend statistics natively using SQLite logic."""
    async with get_db_session() as session:
        total_jobs = await session.scalar(select(func.count()).select_from(JobPosting)) or 0
        curve_balls = await session.scalar(select(func.count()).select_from(JobPosting).where(JobPosting.is_curve_ball == True)) or 0
        strong_matches = await session.scalar(select(func.count()).select_from(JobPosting).where(JobPosting.match_score >= 80)) or 0
        
        # Group by Role
        roles_stmt = select(JobPosting.role_category, func.count(JobPosting.id).label('count')).where(JobPosting.role_category != None).group_by(JobPosting.role_category).order_by(desc('count')).limit(5)
        roles_res = await session.execute(roles_stmt)
        top_roles = [{"role": row[0], "count": row[1]} for row in roles_res]

        # Group by Company
        comp_stmt = select(Company.name, func.count(JobPosting.id).label('count')).join(JobPosting).group_by(Company.name).order_by(desc('count')).limit(5)
        comp_res = await session.execute(comp_stmt)
        top_companies = [{"company": row[0], "count": row[1]} for row in comp_res]

        return {
            "total_jobs_scanned": total_jobs,
            "strong_matches": strong_matches,
            "curve_balls": curve_balls,
            "top_roles": top_roles,
            "top_companies": top_companies
        }

@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest, background_tasks: BackgroundTasks):
    """Update job rating directly via SQLite ID."""
    async with get_db_session() as session:
        job = await session.get(JobPosting, int(req.job_id))
        if not job:
            raise HTTPException(status_code=404, detail="Job ID not found in database.")
            
        job.status = req.status
        job.feedback_comment = req.comment
        await session.commit()

    return {"status": "success", "message": "Feedback recorded."}

def _run_pipeline_thread(resume_path, config):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_pipeline(resume_path=resume_path, preferences=config))
    finally:
        loop.close()

@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    """Trigger the multi-agent Orchestrator DAG as a background thread task."""
    logger.info("Spawning background orchestrator pipeline...")
    config = load_config()
    resume_path = config.get("preferences_path", ".resumes/preferences.md")
    
    # Run in a dedicated thread to ensure Playwright uses ProactorEventLoop on Windows
    background_tasks.add_task(_run_pipeline_thread, resume_path, config)
    return {"status": "started", "message": "Orchestrator pipeline started in background."}

@app.get("/api/scan/status")
async def get_scan_status():
    """Read real-time status direct from the ScanLog table."""
    async with get_db_session() as session:
        stmt = select(ScanLog).order_by(desc(ScanLog.run_time)).limit(1)
        latest_scan = await session.scalar(stmt)
        
        if not latest_scan:
            return {"status": "idle", "completed_companies": []}
            
        return {
            "status": latest_scan.status,
            "jobs_discovered": latest_scan.jobs_discovered,
            "error_message": latest_scan.error_message,
            "completed_companies": [] # Can be implemented via relationships if needed later
        }

@app.get("/api/queries")
async def get_queries():
    return load_config().get("search_queries", [])

@app.post("/api/queries")
async def save_queries(req: QueriesRequest):
    config = load_config()
    config["search_queries"] = req.queries
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return {"status": "success", "queries": config["search_queries"]}

@app.get("/api/config")
async def get_app_config():
    config = load_config()
    return {
        "restrict_to_target_companies": config.get("restrict_to_target_companies", False),
        "scan_interval_hours": config.get("scan_interval_hours", 12),
    }

@app.get("/api/companies")
async def get_active_companies():
    return load_config().get("target_companies", [])

@app.get("/api/master_companies")
async def get_master_companies():
    if os.path.exists("data/companies_db.json"):
        with open("data/companies_db.json", "r", encoding="utf-8") as f:
            return {"companies": json.load(f)}
    return {"companies": []}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)