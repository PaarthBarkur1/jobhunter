import os
import json
import asyncio
import logging
import subprocess
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import List

# Import preference update from job_agent
from job_agent import update_preferences_profile

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("job_hunter_web")

app = FastAPI(title="Job Hunter Dashboard API")

# Global tracking for background scan process
scan_process = None
scheduler_process = None
ollama_process = None
scan_lock = asyncio.Lock()
scheduler_lock = asyncio.Lock()

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
    """Retrieve all daily dates directories."""
    data_dir = "data"
    dates = []
    if os.path.exists(data_dir):
        for item in os.listdir(data_dir):
            if os.path.isdir(os.path.join(data_dir, item)):
                # Ensure it fits YYYY-MM-DD
                if len(item) == 10 and item[4] == '-' and item[7] == '-':
                    dates.append(item)
    # Sort descending (latest dates first)
    dates.sort(reverse=True)
    return dates

@app.get("/api/jobs")
async def get_jobs_for_date(date: str):
    """Retrieve jobs, summary, and current preferences profile for a specific date or all dates combined."""
    jobs = []
    summary = ""
    
    if date == "all":
        # Read the verified persistent all_jobs.json database
        all_jobs_path = "data/all_jobs.json"
        if os.path.exists(all_jobs_path):
            try:
                with open(all_jobs_path, "r", encoding="utf-8") as f:
                    jobs = json.load(f)
            except Exception as e:
                logger.error(f"Error loading all_jobs.json: {e}")
                            
        # Sort aggregated jobs by match score
        jobs.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        summary = "### Combined Job Search History\nShowing all persistent, verified open job postings discovered across all previous scans."
    else:
        jobs_path = os.path.join("data", date, "jobs.json")
        summary_path = os.path.join("data", date, "summary.md")
        
        if os.path.exists(jobs_path):
            try:
                with open(jobs_path, "r", encoding="utf-8") as f:
                    jobs = json.load(f)
                # Sort jobs by match_score descending
                jobs.sort(key=lambda x: x.get("match_score", 0), reverse=True)
            except Exception as e:
                logger.error(f"Error loading jobs.json for date {date}: {e}")
                
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    summary = f.read()
            except Exception as e:
                logger.error(f"Error reading summary.md for date {date}: {e}")
                
    return {
        "date": date,
        "jobs": jobs,
        "summary": summary,
        "preferences": get_preferences_content()
    }

@app.get("/api/trends")
async def get_trends():
    """Aggregate trend statistics across recent daily directories."""
    data_dir = "data"
    role_counts = {}
    company_counts = {}
    total_jobs = 0
    curve_balls = 0
    high_matches = 0
    
    if os.path.exists(data_dir):
        # Scan last 15 days of folders
        folders = [item for item in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, item))]
        folders.sort(reverse=True)
        
        for folder in folders[:15]:
            jobs_path = os.path.join(data_dir, folder, "jobs.json")
            if os.path.exists(jobs_path):
                try:
                    with open(jobs_path, "r", encoding="utf-8") as f:
                        jobs_list = json.load(f)
                    
                    for job in jobs_list:
                        total_jobs += 1
                        
                        # Count matches vs curve balls
                        if job.get("is_curve_ball", False):
                            curve_balls += 1
                        elif job.get("match_score", 0) >= 80:
                            high_matches += 1
                            
                        # Normalize role title
                        title = job.get("title", "Unknown Role").strip()
                        role_counts[title] = role_counts.get(title, 0) + 1
                        
                        # Company count
                        company = job.get("company", "Unknown Company").strip()
                        company_counts[company] = company_counts.get(company, 0) + 1
                except Exception as e:
                    logger.error(f"Error reading trends from {jobs_path}: {e}")
                    
    # Sort dicts
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
    jobs_path = os.path.join("data", req.date, "jobs.json")
    if not os.path.exists(jobs_path):
        raise HTTPException(status_code=404, detail="Data folder for this date not found.")
        
    try:
        with open(jobs_path, "r", encoding="utf-8") as f:
            jobs_list = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load jobs list: {e}")
        
    # Find the job and update it
    job_found = None
    for job in jobs_list:
        if job["id"] == req.job_id:
            job["status"] = req.status
            job["feedback_comment"] = req.comment
            job_found = job
            break
            
    if not job_found:
        raise HTTPException(status_code=404, detail="Job ID not found in daily records.")
        
    # Write back updated jobs.json
    try:
        with open(jobs_path, "w", encoding="utf-8") as f:
            json.dump(jobs_list, f, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save feedback: {e}")
        
    # Load config and promote company to target_companies if thumbs_up
    config = load_config()
    if req.status == "thumbs_up":
        t_cos = config.get("target_companies", [])
        co_name = job_found.get("company", "").strip()
        if co_name and co_name != "N/A" and co_name not in t_cos:
            t_cos.append(co_name)
            config["target_companies"] = t_cos
            
            # Cache career/portal page if it's a direct company-specific portal
            career_pages = config.get("company_career_pages", {})
            job_url = job_found.get("url", "")
            if job_url and ("greenhouse.io" in job_url or "lever.co" in job_url) and co_name not in career_pages:
                career_pages[co_name] = job_url
                config["company_career_pages"] = career_pages
                
            try:
                with open("config.json", "w", encoding="utf-8") as cf:
                    json.dump(config, cf, indent=2)
                logger.info(f"Promoted company '{co_name}' to target list and cached career link.")
            except Exception as e:
                logger.error(f"Failed to save config.json on company promotion: {e}")

    model_name = config.get("ollama_model", "deepseek-r1:1.5b")
    
    # Enqueue background task to update resumes/preferences.md using Ollama
    background_tasks.add_task(
        update_preferences_profile,
        job_title=job_found["title"],
        company=job_found["company"],
        status=req.status,
        comment=req.comment,
        preferences_path=config.get("preferences_path", "resumes/preferences.md"),
        model_name=model_name
    )
    
    return {"status": "success", "message": "Feedback recorded, preference profile update scheduled."}

@app.post("/api/scan")
async def trigger_scan():
    """Spawns the job search agent script in the background."""
    global scan_process
    async with scan_lock:
        if scan_process and scan_process.poll() is None:
            return {"status": "running", "message": "Scan already in progress."}
            
        # Clean up scan_status.json from previous runs if it exists
        status_path = os.path.join("data", "scan_status.json")
        if os.path.exists(status_path):
            try:
                os.remove(status_path)
            except Exception:
                pass

        python_exe = os.path.join(".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = "python"
            
        try:
            logger.info("Spawning background job_agent.py subprocess...")
            scan_process = subprocess.Popen([python_exe, "job_agent.py"])
            return {"status": "started", "message": "Job agent scan started in background."}
        except Exception as e:
            logger.error(f"Failed to start scan process: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start scan: {str(e)}")

@app.get("/api/scan/status")
async def get_scan_status():
    """Check if the background scan is running and read real-time status."""
    global scan_process
    
    # Read the scan status JSON if it exists
    status_data = {}
    status_path = os.path.join("data", "scan_status.json")
    if os.path.exists(status_path):
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                status_data = json.load(f)
        except Exception as e:
            logger.error(f"Error reading scan_status.json: {e}")

    if scan_process is None:
        return {
            "status": status_data.get("status", "idle"),
            "current_company": status_data.get("current_company", ""),
            "completed_companies": status_data.get("completed_companies", [])
        }
        
    poll_res = scan_process.poll()
    if poll_res is None:
        return {
            "status": "running",
            "current_company": status_data.get("current_company", ""),
            "completed_companies": status_data.get("completed_companies", [])
        }
    else:
        # Completed
        exit_code = poll_res
        final_status = "completed" if exit_code == 0 else "failed"
        
        # Clean up scan_status.json after completion so subsequent checks don't see stale running state
        if os.path.exists(status_path):
            try:
                os.remove(status_path)
            except Exception:
                pass
                
        return {
            "status": final_status,
            "exit_code": exit_code,
            "current_company": "",
            "completed_companies": status_data.get("completed_companies", [])
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
    """Kill the active job agent search process tree."""
    global scan_process
    async with scan_lock:
        if not scan_process or scan_process.poll() is not None:
            return {"status": "idle", "message": "No scan is currently running."}
            
        try:
            logger.info(f"Terminating scan process tree with PID {scan_process.pid}...")
            # Use taskkill to kill process tree on Windows
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(scan_process.pid)], capture_output=True)
            scan_process = None
            return {"status": "killed", "message": "Scan process tree terminated successfully."}
        except Exception as e:
            logger.error(f"Failed to kill scan process tree: {e}")
            try:
                # Fallback to standard terminate
                scan_process.terminate()
                scan_process = None
                return {"status": "killed", "message": "Scan process terminated via fallback."}
            except Exception as fe:
                raise HTTPException(status_code=500, detail=f"Failed to terminate scan: {fe}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
