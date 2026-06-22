import os
import re
import json
import asyncio
import logging
import datetime
import shutil
from typing import List, Optional
from pydantic import BaseModel, Field
import ollama
from openpyxl import Workbook, load_workbook

from career_pages import get_career_url_map, get_career_config, get_all_navigation_instructions

# MCP Client SDK Imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("job_agent")

# ==========================================
# PYDANTIC SCHEMAS (Forced Structured Outputs)
# ==========================================
class JobDetails(BaseModel):
    is_job_posting: bool = Field(description="True if the text is a specific job posting/description, False if it is a general page, list, or error.")
    title: str = Field(description="The formal job title or role, or 'N/A' if not a job posting")
    company: str = Field(description="The name of the hiring organization or company, or 'N/A'")
    required_skills: List[str] = Field(description="Core technical or domain skills listed. Empty list if none.")
    experience_level: str = Field(description="Required minimum years of experience or seniority level, or 'N/A'")
    explicit_salary: Optional[str] = Field(None, description="Explicit salary stated in text, e.g. '30 LPA', '₹20,00,000', '$120,000'")
    location: str = Field(description="Job location, e.g., 'Bengaluru', 'Remote', 'Mumbai', or 'N/A'")
    role: str = Field(description="Specific role category or specialization, e.g., 'Quant Developer', 'Data Scientist', 'Machine Learning Engineer', or 'N/A'")
    description: str = Field(description="Brief 2-3 sentence description of the job responsibilities and highlights.")
    posted_date: Optional[str] = Field(None, description="The date the job was posted, if explicitly stated or inferred from text, e.g. '2026-05-10', '3 days ago', 'October 2025', or 'Unknown'.")

class SalaryEstimation(BaseModel):
    estimated_salary_range: str = Field(description="Estimated salary range or amount, e.g. '12-15 LPA', '₹15,00,000 per annum', '$100k', or 'Unknown'")
    reason: str = Field(description="Brief reason or source snippet for the estimation")

class JobMatchEvaluation(BaseModel):
    score: int = Field(description="Match score between 0 and 100 representing how well candidate profile matches the job requirements.")
    reason: str = Field(description="A brief 1-2 sentence explanation of the rating.")
    is_curve_ball: bool = Field(description="True if the job is slightly outside the candidate's core domain/tech stack but represents a high-potential adjacent opportunity. False otherwise.")
    curve_ball_reason: Optional[str] = Field(None, description="If is_curve_ball is True, brief reason why this adjacent role is worth exploring.")

class RefinedConfig(BaseModel):
    search_queries: List[str] = Field(description="List of 5-15 highly refined search query strings optimized for the candidate. Use google/linkedin/indeed search syntax e.g., site:linkedin.com/jobs/view 'quant researcher' India. Include India and Remote options. Avoid target company names in queries, keep query strings generic or focused on target roles.")
    target_companies: List[str] = Field(description="List of target companies (e.g. Goldman Sachs, Uber, Google, Jane Street, Tower Research, etc.), retaining good ones and removing disliked ones.")

class JobRelevance(BaseModel):
    index: int = Field(description="The exact 'Index' number of the job from the input list (e.g. 1, 2, 3, etc.). Do not offset or shift the index.")
    is_relevant: bool = Field(description="True if the job title, company, or snippet suggests it is a match for the candidate's preferences, target roles, locations, and experience level. False if it is in an avoided domain, location, or is a bad company match.")
    reason: str = Field(description="A short 1-sentence explanation of why it was kept or rejected.")

class BatchFilterResponse(BaseModel):
    evaluations: List[JobRelevance] = Field(description="Evaluations for each job in the batch.")

# ==========================================
# CURRENCY & SALARY PARSER UTILITIES
# ==========================================
def parse_salary_to_lpa(salary_str: str) -> float:
    """Parses a salary string and returns the value in LPA (Lakhs Per Annum) in INR."""
    if not salary_str or salary_str.lower() in ["none", "n/a", "null", "unknown", "unspecified"]:
        return 0.0
    
    s = salary_str.lower()
    # Find all decimal/comma numbers
    numbers = re.findall(r'\d+(?:,\d+)*(?:\.\d+)?', s)
    if not numbers:
        return 0.0
    
    # Clean commas and parse to float
    val = float(numbers[0].replace(',', ''))
    # Fix the 0 lower bound range issue (e.g. 0-8 Lakhs -> take 8)
    if val == 0.0 and len(numbers) > 1:
        val = float(numbers[1].replace(',', ''))
    
    # Identify indicators
    is_usd = any(c in s for c in ['$', 'usd', 'eur', 'gbp', '€', '£'])
    is_hourly = any(h in s for h in ['/hr', 'hour', 'hr'])
    is_monthly = any(m in s for m in ['/mo', 'month', 'pm'])
    
    # Calculate annual value in currency
    if is_hourly:
        annual_val = val * 2000  # Assume 2000 hours/year
    elif is_monthly:
        annual_val = val * 12
    else:
        # Standard annual salary. Handle K suffixes (e.g. 120k)
        if re.search(r'\b\d+\s*k\b|\b\d+k\b', s) and val < 1000:
            annual_val = val * 1000
        else:
            annual_val = val
            
    # Check if value is already in Lakhs (India)
    has_lakh_indicator = any(re.search(rf'\b{word}\b', s) for word in ['lpa', 'lakh', 'lakhs', 'lac', 'lacs'])
    
    if val < 200 and has_lakh_indicator:
        # Already in Lakhs
        annual_in_inr = annual_val * 100000
    else:
        # It's raw amount
        if is_usd:
            annual_in_inr = annual_val * 83.0  # 1 USD = 83 INR
        else:
            annual_in_inr = annual_val
            
    # Convert INR to Lakhs
    lpa = annual_in_inr / 100000.0
    return round(lpa, 1)

def is_posted_over_6_months_ago(posted_date_str: str) -> bool:
    """
    Returns True if the job posting date string indicates the job is older than 6 months (180 days).
    """
    if not posted_date_str or posted_date_str.lower() in ["unknown", "n/a", "none", "null"]:
        return False
        
    s = posted_date_str.lower().strip()
    
    # 1. Parse relative time offsets
    # Check years
    if "year" in s:
        # e.g., "1 year ago", "2 years ago", "last year"
        return True
        
    # Check months
    month_match = re.search(r'(\d+)\s*month', s)
    if month_match:
        try:
            months = int(month_match.group(1))
            return months >= 6
        except Exception:
            pass
        
    # Weeks, days, hours are always under 6 months
    if "week" in s or "day" in s or "hour" in s or "yesterday" in s or "today" in s:
        return False
        
    # 2. Parse absolute dates (e.g. "2024-05-12", "Oct 12 2025", "12/23/2025")
    year_match = re.search(r'\b(20\d{2})\b', s)
    if year_match:
        try:
            year = int(year_match.group(1))
            today = datetime.date.today()
            if year < today.year - 1:
                return True
                
            parsed_date = None
            # Standard ISO "YYYY-MM-DD"
            iso_match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
            if iso_match:
                parsed_date = datetime.date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
            else:
                # Try strptime with some formats
                for fmt in ["%B %Y", "%b %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                    try:
                        clean_s = re.sub(r'th|st|nd|rd', '', s)
                        parsed_dt = datetime.datetime.strptime(clean_s, fmt)
                        parsed_date = parsed_dt.date()
                        break
                    except ValueError:
                        continue
            
            if parsed_date:
                age_days = (today - parsed_date).days
                return age_days >= 180
        except Exception:
            pass
            
    return False

def update_scan_status(current_company: str, completed_companies: List[str], status: str = "running"):
    try:
        os.makedirs("data", exist_ok=True)
        status_path = os.path.join("data", "scan_status.json")
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump({
                "status": status,
                "current_company": current_company,
                "completed_companies": completed_companies
            }, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to update scan_status.json: {e}")

# ==========================================
# DATED DIRECTORY CLEANUP UTILITY
# ==========================================
def clean_old_directories(data_dir: str = "data", max_days: int = 30):
    """Deletes directories under data_dir older than max_days."""
    if not os.path.exists(data_dir):
        return
    
    today = datetime.date.today()
    logger.info(f"Running cleanup on '{data_dir}' folder. Deleting folders older than {max_days} days...")
    
    for item in os.listdir(data_dir):
        item_path = os.path.join(data_dir, item)
        if os.path.isdir(item_path):
            # Try to parse item as YYYY-MM-DD
            try:
                folder_date = datetime.datetime.strptime(item, "%Y-%m-%d").date()
                age = (today - folder_date).days
                if age > max_days:
                    logger.info(f"Deleting old folder: {item} (Age: {age} days)")
                    shutil.rmtree(item_path)
            except ValueError:
                # Folder name is not in YYYY-MM-DD format, skip it
                pass

def save_to_excel_rolling(job: dict, excel_path: str):
    """Appends a single job to the Excel file, creating it with headers if it doesn't exist."""
    headers = [
        "Title", "Company", "URL", "Source", "Expected CTC (LPA)", 
        "Required Skills", "Experience Level", "Match Score", "Match Reason", 
        "Location", "Role", "Description", "Posted Date"
    ]
    
    if os.path.exists(excel_path):
        try:
            wb = load_workbook(excel_path)
            ws = wb.active
        except Exception:
            wb = Workbook()
            ws = wb.active
            ws.title = "Jobs"
            ws.append(headers)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Jobs"
        ws.append(headers)
        
    ws.append([
        job.get("title", "N/A"),
        job.get("company", "N/A"),
        job.get("url", "N/A"),
        job.get("source", "N/A"),
        job.get("ctc", 0.0),
        ", ".join(job.get("required_skills", [])),
        job.get("experience_level", "N/A"),
        job.get("match_score", 0),
        job.get("match_reason", "N/A"),
        job.get("location", "N/A"),
        job.get("role", "N/A"),
        job.get("description", "N/A"),
        job.get("posted_date", "Unknown")
    ])
    
    try:
        wb.save(excel_path)
        logger.info(f"Incrementally saved job '{job.get('title')}' at '{job.get('company')}' to Excel.")
    except Exception as e:
        logger.error(f"Error saving rolling Excel: {e}")

# ==========================================
# PREFERENCES UPDATE ROUTINE
# ==========================================
async def update_preferences_profile(job_title: str, company: str, status: str, comment: str, preferences_path: str = ".resumes/preferences.md", model_name: str = "deepseek-r1:1.5b"):
    """
    Updates the preferences markdown file based on user feedback.
    Called asynchronously when user clicks thumbs up/down.
    """
    os.makedirs(os.path.dirname(preferences_path), exist_ok=True)
    
    current_profile = ""
    if os.path.exists(preferences_path):
        try:
            with open(preferences_path, "r", encoding="utf-8") as f:
                current_profile = f.read()
        except Exception as e:
            logger.error(f"Error reading preferences file: {e}")
            
    if not current_profile.strip():
        current_profile = "# Job Preferences Profile\n\n## Likes\n- None specified yet.\n\n## Dislikes\n- None specified yet.\n"

    prompt = f"""
    You are an AI assistant managing a candidate's career preferences.
    Update the candidate's current preferences markdown profile based on new user feedback.
    
    Current Preferences Profile:
    {current_profile}
    
    New Feedback:
    - Job: {job_title} at {company}
    - Rating: {status.upper()} (User gave a {"thumbs up" if status == "thumbs_up" else "thumbs down"})
    - User Comment on why: "{comment}"
    
    Please update the current profile. Integrate the new feedback:
    1. If the user dislikes something (thumbs down), add details to 'Dislikes' (e.g. what domain, technology, or company trait to avoid).
    2. If the user likes something (thumbs up), add details to 'Likes'.
    3. Keep the markdown well-structured and concise. Clean up duplicates. Return ONLY the complete updated Markdown text. Do not write code fences like ```markdown.
    """
    
    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a professional assistant. Output ONLY the updated Markdown profile. Do not include chat explanations or markdown blocks."},
                {"role": "user", "content": prompt}
            ]
        )
        updated_content = response['message']['content'].strip()
        
        # Clean any wrapping code blocks that the LLM might have outputted despite instructions
        if updated_content.startswith("```markdown"):
            updated_content = updated_content[11:]
        if updated_content.startswith("```"):
            updated_content = updated_content[3:]
        if updated_content.endswith("```"):
            updated_content = updated_content[:-3]
        updated_content = updated_content.strip()

        with open(preferences_path, "w", encoding="utf-8") as f:
            f.write(updated_content)
        logger.info(f"Preferences profile '{preferences_path}' successfully updated.")
    except Exception as e:
        logger.error(f"Error updating preferences profile: {e}")

# ==========================================
# MAIN EXECUTION ROUTINE
# ==========================================
# ==========================================
# ROLLING SAVE UTILITIES
# ==========================================
def save_to_json_rolling(job: dict, json_path: str):
    """Appends/updates a single job in the JSON list and saves it."""
    jobs_list = []
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                jobs_list = json.load(f)
        except Exception:
            pass
            
    # Check if job already exists
    exists = False
    for i, j in enumerate(jobs_list):
        if j.get("id") == job.get("id"):
            jobs_list[i] = job
            exists = True
            break
            
    if not exists:
        jobs_list.append(job)
        
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(jobs_list, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving rolling JSON: {e}")

def is_aggregator_list_page(url: str) -> bool:
    """Returns True if the URL points to a job aggregator search result or listing category page."""
    url_lower = url.lower()
    
    # Direct job post patterns we want to preserve
    if any(p in url_lower for p in ["/jobs/view/", "/viewjob", "naukri.com/job-listings-", "greenhouse.io/", "lever.co/"]):
        return False
        
    patterns = [
        "/jobs/search", "search?", "query=", "?q=", "search_query=",
        "/jobs-in-", "/jobs-at-", "/jobs-for-",
        "indeed.com/q-", "indeed.com/l-",
        "simplyhired.co.in/search",
        "naukri.com/", "careerjet.co.in/",
        "amazon.jobs/content/", "amazon.jobs/en/search",
        "linkedin.com/jobs/", "glassdoor.co.in/job/"
    ]
    
    for pattern in patterns:
        if pattern in url_lower:
            return True
            
    return False

async def process_discovered_url(url: str, title: str, snippet: str, session, config: dict, model_name: str, salary_threshold: float, resume_text: str, preferences_text: str, daily_dir: str, company_hint: str = "") -> Optional[dict]:
    # Check if we already processed this URL to avoid duplicates
    jobs_json_path = os.path.join(daily_dir, "jobs.json")
    if os.path.exists(jobs_json_path):
        try:
            with open(jobs_json_path, "r", encoding="utf-8") as f:
                existing_jobs = json.load(f)
                if any(j.get("url") == url for j in existing_jobs):
                    logger.info(f"Already processed URL {url}. Skipping.")
                    return None
        except Exception:
            pass

    # Extract source domain
    source_domain = "Web Search"
    domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    if domain_match:
        source_domain = domain_match.group(1)
        
    cleaned_text = ""
    try:
        page_res = await session.call_tool("fetch_web_page", arguments={"url": url})
        cleaned_text = page_res.content[0].text
    except Exception as e:
        logger.warning(f"Failed to scrape webpage directly: {e}")
        
    if not cleaned_text.strip() or cleaned_text.startswith("Error fetching") or len(cleaned_text.strip()) < 100:
        if snippet:
            logger.warning("Falling back to search snippet...")
            cleaned_text = f"Title: {title}\nJob Posting Snippet Details:\n{snippet}"
        else:
            logger.warning(f"Skipping {url} due to fetch error.")
            return None

    # Inject career portal navigation context when scraping company sites
    nav_context = ""
    if company_hint:
        cfg = get_career_config(company_hint)
        if cfg:
            nav_context = f"\n\nCAREER PORTAL NAVIGATION CONTEXT for {cfg.company}:\n{cfg.model_instructions.strip()}\n"

    # Parse structural job details
    extract_prompt = f"Analyze the following scraped webpage text and extract structured job details if it is a job description:{nav_context}\n\n{cleaned_text}"
    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a precise job data miner. Parse the text and output EXACTLY a JSON structure matching the schema. If the text does not contain a job posting, mark is_job_posting as false."},
                {"role": "user", "content": extract_prompt}
            ],
            format=JobDetails.model_json_schema()
        )
        content = response.get('message', {}).get('content', '')
        try:
            job_metrics = JobDetails.model_validate_json(content)
        except Exception as ve:
            # Save raw response for debugging
            try:
                os.makedirs("data", exist_ok=True)
                raw_path = os.path.join("data", f"last_ollama_raw_{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.txt")
                with open(raw_path, "w", encoding="utf-8") as rf:
                    rf.write(content)
                logger.error(f"Invalid JSON from Ollama saved to {raw_path}: {ve}")
            except Exception:
                logger.error(f"Invalid JSON from Ollama and failed saving raw response: {ve}")
            # Retry with a compact extraction prompt (shorter)
            try:
                short_text = (cleaned_text[:3500] + "...") if len(cleaned_text) > 3500 else cleaned_text
                retry_prompt = f"Extract only these fields as JSON: is_job_posting,title,company,required_skills,experience_level,explicit_salary,location,role,description,posted_date. Text:\n\n{short_text}"
                retry_resp = ollama.chat(
                    model=model_name,
                    messages=[
                        {"role":"system","content":"Output ONLY valid JSON matching the requested keys. No extra text."},
                        {"role":"user","content": retry_prompt}
                    ],
                    format=JobDetails.model_json_schema()
                )
                retry_content = retry_resp.get('message', {}).get('content', '')
                job_metrics = JobDetails.model_validate_json(retry_content)
            except Exception as e2:
                err_str = str(e2).lower()
                if "connection" in err_str or "urllib3" in err_str or "http" in err_str or "refused" in err_str:
                    logger.critical(f"Ollama server is unreachable during retry! Aborting scan: {e2}")
                    raise e2
                logger.error(f"Retry parsing failed: {e2}")
                return None

    except Exception as e:
        err_str = str(e).lower()
        if "connection" in err_str or "urllib3" in err_str or "http" in err_str or "refused" in err_str:
            logger.critical(f"Ollama server is unreachable! Aborting scan: {e}")
            raise e
        logger.error(f"Error calling Ollama: {e}")
        return None

    if not job_metrics.is_job_posting:
        logger.info("Webpage is not a job posting. Skipping.")
        return None

    # Gatekeeper Check: Date Posted (Skip if older than 6 months / 180 days)
    if job_metrics.posted_date and is_posted_over_6_months_ago(job_metrics.posted_date):
        logger.info(f"⛔ Gated: Job posted date '{job_metrics.posted_date}' is 6 months or more ago. Skipping.")
        return None
        
    logger.info(f"Found Job: '{job_metrics.title}' at '{job_metrics.company}'")
    
    # Defaults
    location = job_metrics.location if job_metrics.location else "N/A"
    role = job_metrics.role if job_metrics.role else "N/A"
    description = job_metrics.description if job_metrics.description else "N/A"

    # Gatekeeper Check: Calculate Compensation
    estimated_pay = 0.0
    if job_metrics.explicit_salary:
        estimated_pay = parse_salary_to_lpa(job_metrics.explicit_salary)
        logger.info(f"Parsed Explicit Salary: {job_metrics.explicit_salary} -> ~{estimated_pay} LPA")
        
    # Online salary estimation and gating disabled as requested by user.
    # We will still parse explicit salary if it is mentioned in the job post,
    # but we won't query search engines or filter out roles below the threshold.
    
    # if estimated_pay == 0.0:
    #     # Look up salary info on web using MCP
    #     salary_query = f"{job_metrics.title} at {job_metrics.company} average salary India Glassdoor AmbitionBox"
    #     logger.info(f"No explicit salary. Looking up compensation info: '{salary_query}'")
    #     try:
    #         salary_search = await session.call_tool("search_web", arguments={"query": salary_query})
    #         salary_snippets = salary_search.content[0].text
    #         
    #         salary_prompt = f"Given these search snippets, estimate the median average salary in India for a '{job_metrics.title}' at '{job_metrics.company}'. Return your best estimate using the schema:\n\n{salary_snippets}"
    #         salary_res = ollama.chat(
    #             model=model_name,
    #             messages=[
    #                 {"role": "system", "content": "Analyze the salary snippets and return the estimated salary range as a string using the JSON schema."},
    #                 {"role": "user", "content": salary_prompt}
    #             ],
    #             format=SalaryEstimation.model_json_schema()
    #         )
    #         salary_data = SalaryEstimation.model_validate_json(salary_res['message']['content'])
    #         estimated_pay = parse_salary_to_lpa(salary_data.estimated_salary_range)
    #         logger.info(f"Estimated compensation from web: ~{estimated_pay} LPA ({salary_data.reason})")
    #     except Exception as e:
    #         err_str = str(e).lower()
    #         if "connection" in err_str or "urllib3" in err_str or "http" in err_str or "refused" in err_str:
    #             logger.critical(f"Ollama server is unreachable during salary estimation! Aborting scan: {e}")
    #             raise e
    #         logger.error(f"Error estimating salary: {e}")
    #         estimated_pay = 0.0
    # 
    # # Check salary gate
    # if estimated_pay > 0.0 and estimated_pay < salary_threshold:
    #     logger.info(f"⛔ Gated: Compensation ~{estimated_pay} LPA falls below threshold of {salary_threshold} LPA. Skipping.")
    #     return None

    # Evaluate Profile Match & Preferences (Strict Dislikes)
    if not resume_text:
        logger.info("Skipping resume match evaluation because no resumes were loaded.")
        return None
        
    logger.info("Evaluating candidate alignment against resumes and preference profile...")
    career_nav_guide = get_all_navigation_instructions()
    resume_snip_len = config.get('resume_max_chars_in_prompt', 1000) if isinstance(config, dict) else 1000
    trimmed_resume = (resume_text[:resume_snip_len] + '...') if resume_text and len(resume_text) > resume_snip_len else (resume_text or '')

    match_prompt = f"""
    Evaluate structural alignment between Candidate Resumes, Preferences, and the Target Job details.
    
    Candidate Resumes:
    {trimmed_resume}
    
    Candidate Preferences & Dislikes:
    {preferences_text if preferences_text else "No specific preferences set yet."}
    
    Company Career Portal Reference (use when evaluating company-specific roles):
    {career_nav_guide[:3000]}
    
    Target Job:
    - Title: {job_metrics.title}
    - Company: {job_metrics.company}
    - Skills: {', '.join(job_metrics.required_skills)}
    - Experience/Seniority: {job_metrics.experience_level}
    - Location: {location}
    - Role: {role}
    
    INSTRUCTIONS:
    1. If the job is NOT located in India or Remote (e.g., it is onsite in US, UK, Europe, or other foreign regions), you MUST evaluate it with a match score of 0% and explain that the job is not in the candidate's target location (India or Remote).
    2. If the job violates candidate dislikes (e.g. onsite/hybrid when remote is preferred, or in an avoided domain/tech stack), you MUST evaluate it with a match score of 0% and reason explaining the preference mismatch.
    3. If the job is slightly outside the candidate's core domain/tech stack but represents a high-potential high-paying opportunity, classify it as a 'Curve Ball' by setting `is_curve_ball` to True. Set its match score to 80, and explain why in `curve_ball_reason`.
    """
    
    try:
        match_res = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a professional recruiter. Evaluate the alignment. Be strict about candidate dislikes. Output JSON matching the schema."},
                {"role": "user", "content": match_prompt}
            ],
            format=JobMatchEvaluation.model_json_schema()
        )
        match_data = JobMatchEvaluation.model_validate_json(match_res['message']['content'])
        logger.info(f"Candidate Match Score: {match_data.score}% | Curve Ball: {match_data.is_curve_ball} - Reason: {match_data.reason}")
    except Exception as e:
        err_str = str(e).lower()
        if "connection" in err_str or "urllib3" in err_str or "http" in err_str or "refused" in err_str:
            logger.critical(f"Ollama server is unreachable during match evaluation! Aborting scan: {e}")
            raise e
        logger.error(f"Error evaluating match: {e}")
        return None

    # Generate unique ID
    job_id = re.sub(r'[^a-z0-9]', '_', f"{job_metrics.company}_{job_metrics.title}".lower())
    
    job_result = {
        "id": job_id,
        "title": job_metrics.title,
        "company": job_metrics.company,
        "url": url,
        "source": source_domain,
        "ctc": estimated_pay,
        "required_skills": job_metrics.required_skills,
        "experience_level": job_metrics.experience_level,
        "location": location,
        "role": role,
        "description": description,
        "posted_date": job_metrics.posted_date if job_metrics.posted_date else "Unknown",
        "match_score": match_data.score,
        "match_reason": match_data.reason,
        "is_curve_ball": match_data.is_curve_ball,
        "curve_ball_reason": match_data.curve_ball_reason,
        "status": "unrated",
        "feedback_comment": ""
    }
    
    # Save incrementally
    save_to_json_rolling(job_result, jobs_json_path)
    excel_path = os.path.join(daily_dir, "jobs.xlsx")
    save_to_excel_rolling(job_result, excel_path)
    
    return job_result

# ==========================================
# MAIN EXECUTION ROUTINE
# ==========================================
DEFAULT_CONFIG = {
    "ollama_model": "deepseek-r1:1.5b",
    "target_compensation_threshold_lpa": 0,
    "resumes_dir": ".resumes",
    "search_queries": [
        "data scientist",
        "applied scientist",
        "Credit data scientist",
        "quant analyst",
        "site:linkedin.com/jobs/view \"quant researcher\" India",
        "site:linkedin.com/jobs/view \"data scientist\" India",
        "site:linkedin.com/jobs/view \"applied researcher\" India",
        "site:indeed.com/viewjob \"quant researcher\" India",
        "site:indeed.com/viewjob \"data scientist\" India",
        "site:indeed.com/viewjob \"applied researcher\" India",
        "site:boards.greenhouse.io python India",
        "site:lever.co quant researcher",
        "site:reddit.com/r/cscareerquestionsIN \"hiring\" OR \"who is hiring\"",
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
        "IMC Trading",
        "eBay"
    ],
    "direct_job_urls": [],
    "jobs_digest_path": "jobs_digest.md",
    "restrict_to_target_companies": False,
    "max_additional_companies": 30,
    "max_jobs_to_process": 50,
    "company_career_pages": {},
    "scan_interval_hours": 6,
    "career_scrape_max_per_company": 15
}

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
            
    # Check if critical lists/keys are missing or empty
    modified = False
    for k, v in DEFAULT_CONFIG.items():
        if k not in config or (isinstance(v, list) and not config.get(k)) or (isinstance(v, dict) and not config.get(k)):
            config[k] = v
            modified = True
            
    # Ensure hardcoded company career URLs are present by default and their companies are listed
    try:
        hardcoded = get_career_url_map()
        if hardcoded:
            career_pages = config.get("company_career_pages", {}) or {}
            target_companies = config.get("target_companies", []) or []
            for co, url in hardcoded.items():
                if co not in career_pages:
                    career_pages[co] = url
                    modified = True
                # Ensure company appears in target_companies (case-insensitive)
                if not any(co.lower() == existing.lower() for existing in target_companies):
                    target_companies.append(co)
                    modified = True
            config["company_career_pages"] = career_pages
            config["target_companies"] = target_companies
    except Exception as e:
        logger.error(f"Failed merging hardcoded career urls into config: {e}")
            
    if modified:
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            logger.info("config.json was missing or empty keys. Restored defaults successfully.")
        except Exception as e:
            logger.error(f"Failed to save default config.json: {e}")
            
    return config

async def optimize_search_queries_and_config(resume_text: str, preferences_text: str, config: dict, model_name: str) -> dict:
    """
    Invokes Ollama to read candidate profile and preferences, dynamically optimizes search queries 
    and target companies, validates the updates, and saves them back to config.json.
    """
    logger.info("Starting proactive search query and target company optimization...")
    if not resume_text and not preferences_text:
        logger.warning("No resume or preferences available for search optimization. Skipping.")
        return config

    prompt = f"""
    You are an expert recruiter and career agent managing a job search configuration.
    Analyze the candidate's Resume and Preferences Profile, then optimize the "search_queries" and "target_companies" in the config.

    Candidate Resume Profile:
    {resume_text[:4000]}

    Candidate Preferences Profile (Likes & Dislikes):
    {preferences_text}

    Current Search Queries:
    {json.dumps(config.get("search_queries", []), indent=2)}

    Current Target Companies:
    {json.dumps(config.get("target_companies", []), indent=2)}

    INSTRUCTIONS:
    1. Output a JSON object containing "search_queries" and "target_companies".
    2. "search_queries": Focus on target roles, locations (e.g. India or Remote), and experience level. Create 5-15 search queries. Avoid referencing company names directly in general query strings. Keep queries clean and generic (e.g. site:linkedin.com/jobs/view "data scientist" India).
    3. "target_companies": Retain target companies that match candidate profile. Remove companies explicitly disliked (e.g., Millennium Management, Infosys). Add any companies from liked postings.
    4. Keep the list formatted exactly as the schema. Do not write any other explanation.
    """

    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a professional recruiting configurator. Return JSON matching the schema precisely. Validate location and dislikes."},
                {"role": "user", "content": prompt}
            ],
            format=RefinedConfig.model_json_schema()
        )
        refined_data = RefinedConfig.model_validate_json(response['message']['content'])
        
        # Sandbox / Sanitization logic:
        # Clean queries and restrict to safe formats, max 25 queries, max 30 companies.
        cleaned_queries = []
        for q in refined_data.search_queries:
            if not isinstance(q, str):
                continue
            q_clean = q.strip()
            # Ensure query is not empty and doesn't contain dangerous shell characters
            if len(q_clean) > 3 and not any(char in q_clean for char in [';', '|', '&', '$', '`', '<', '>', '\n', '\r']):
                cleaned_queries.append(q_clean)
        
        cleaned_companies = []
        for c in refined_data.target_companies:
            if not isinstance(c, str):
                continue
            c_clean = c.strip()
            if len(c_clean) > 2 and not any(char in c_clean for char in [';', '|', '&', '$', '`', '<', '>', '\n', '\r']):
                # Double-check that we are not adding explicitly disliked companies
                c_lower = c_clean.lower()
                disliked = False
                for term in ["millennium", "infosys", "wipro", "tcs", "cognizant"]:
                    if term in c_lower:
                        disliked = True
                        break
                if not disliked:
                    cleaned_companies.append(c_clean)
                    
        if cleaned_queries:
            config["search_queries"] = cleaned_queries[:25]
            logger.info(f"Refined search queries (count: {len(config['search_queries'])}): {config['search_queries']}")
        if cleaned_companies:
            existing_companies = config.get("target_companies", [])
            disliked_terms = ["millennium", "infosys", "wipro", "tcs", "cognizant"]
            filtered_existing = []
            for c in existing_companies:
                c_lower = c.lower()
                if not any(term in c_lower for term in disliked_terms):
                    filtered_existing.append(c)
            
            merged_companies = list(filtered_existing)
            for c in cleaned_companies:
                if c.lower() not in [x.lower() for x in merged_companies]:
                    merged_companies.append(c)
                    
            config["target_companies"] = merged_companies[:30]
            logger.info(f"Refined target companies (count: {len(config['target_companies'])}): {config['target_companies']}")
            
        # Write back safely to config.json
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            logger.info("config.json successfully optimized by Ollama.")
        except Exception as write_err:
            logger.error(f"Failed to save optimized config.json: {write_err}")
            
    except Exception as e:
        logger.error(f"Failed to optimize search configuration: {e}")
        
    return config

async def filter_jobs_batch_smart(job_list: List[dict], resume_text: str, preferences_text: str, model_name: str) -> List[dict]:
    """
    Groups compiled jobs into batches and asks Ollama to pre-filter them based on
    resume alignment and candidate preferences. This filters out irrelevant divisions/roles
    before running the full scraping/processing pipeline.
    """
    if not job_list:
        logger.info("No jobs to filter.")
        return []

    logger.info(f"Starting smart batch filtering of {len(job_list)} compiled job listings...")
    
    # Check if we have profile information to filter with
    if not resume_text and not preferences_text:
        logger.warning("No resumes or preferences available for smart batch filtering. Skipping pre-filter.")
        return job_list

    filtered_jobs = []
    config_local = load_config()
    batch_size = config_local.get("smart_filter_batch_size", 5)
    fallback_subbatch = config_local.get("smart_filter_fallback_size", 5)
    resume_snip_len = config_local.get("resume_max_chars_in_prompt", 1000)
    
    for i in range(0, len(job_list), batch_size):
        batch = job_list[i:i + batch_size]
        logger.info(f"Filtering batch [{i // batch_size + 1}/{(len(job_list) - 1) // batch_size + 1}] (Size: {len(batch)})...")
        
        # Prepare list of jobs for prompt as a clean string list
        jobs_input_list = []
        for idx, job in enumerate(batch, 1):
            jobs_input_list.append(
                f"Job Index: {idx}\n"
                f"Title: {job.get('title', 'N/A')}\n"
                f"Company: {job.get('company_hint', 'Unknown')}\n"
                f"Snippet: {job.get('snippet', '')[:300]}\n"
                f"Source: {job.get('source', 'Web Search')}\n"
                f"---"
            )
        jobs_input_str = "\n".join(jobs_input_list)
        trimmed_resume = resume_text[:resume_snip_len] if resume_text else ""
            
        prompt = f"""
        You are a screening assistant checking a list of job postings for a candidate.
        
        Candidate Target Profile:
        - Target Roles: Quantitative Researcher, Quant Developer, Data Scientist, Machine Learning Scientist, Software Engineer.
        - Target Location: India (including cities like Bengaluru/Bangalore, Hyderabad, Pune, Gurgaon/Gurugram, Mumbai) or Remote.
        - Avoided/Disliked:
          * Trading firm culture (specifically Millennium Management).
          * Indian outsourcing/services firms (specifically Infosys, TCS, Wipro).
          * Onsite jobs in foreign countries (like US, NYC, London) unless they are Remote.

        Candidate Resume Summary:
        {trimmed_resume}

        Candidate Preferences:
        {preferences_text}

        List of Job Listings to Screen:
        {jobs_input_str}

        INSTRUCTIONS:
        For each job in the list:
        1. Set `is_relevant` to True ONLY if the role matches the candidate's target roles, is in India (or Remote), matches their experience level, and does not violate the dislikes.
        2. Set `is_relevant` to False if the job is onsite in a foreign country (like NYC/US), is at a disliked company (like Millennium or Infosys), or is in an irrelevant field.
        3. Do NOT blacklist target companies (like Jane Street, Google, or Uber) just because a historical posting at that company was thumbs-downed in preferences. Only skip companies explicitly disliked by name (Millennium Management, Infosys).
        4. Make sure the output `index` matches the `Job Index` of that specific job EXACTLY. Do not offset or shift the indices.
        5. Output the results strictly matching the JSON schema.
        """
        
        try:
            response = ollama.chat(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a precise screening agent. Filter out irrelevant roles and locations. Output JSON matching the schema."},
                    {"role": "user", "content": prompt}
                ],
                format=BatchFilterResponse.model_json_schema()
            )
            result = BatchFilterResponse.model_validate_json(response['message']['content'])
            
            # Map index-based responses back to original jobs
            relevance_map = {eval_item.index: eval_item for eval_item in result.evaluations}
            
            for idx, job in enumerate(batch, 1):
                eval_item = relevance_map.get(idx)
                if eval_item:
                    if eval_item.is_relevant:
                        logger.info(f"✅ Kept: '{job.get('title')}' at '{job.get('company_hint', 'N/A')}' - Reason: {eval_item.reason}")
                        filtered_jobs.append(job)
                    else:
                        logger.info(f"❌ Skipped: '{job.get('title')}' at '{job.get('company_hint', 'N/A')}' - Reason: {eval_item.reason}")
                else:
                    # Fallback if Ollama missed an index: keep it to be safe
                    logger.warning(f"⚠️ Index {idx} not evaluated by Ollama. Defaulting to keep.")
                    filtered_jobs.append(job)
                    
        except Exception as batch_err:
            logger.error(f"Error filtering batch of jobs: {batch_err}. Attempting fallback with smaller sub-batches.")
            # Try splitting this batch into smaller sub-batches to avoid context-size and formatting errors
            sub_size = fallback_subbatch if fallback_subbatch and fallback_subbatch > 0 else max(1, batch_size // 4)
            for j in range(0, len(batch), sub_size):
                sub_batch = batch[j:j+sub_size]
                logger.info(f"Retrying sub-batch [{j // sub_size + 1}/{(len(batch) - 1) // sub_size + 1}] (Size: {len(sub_batch)})...")
                # Prepare sub-batch prompt
                sub_jobs_input_list = []
                for idx, job in enumerate(sub_batch, 1):
                    sub_jobs_input_list.append(
                        f"Job Index: {idx}\n"
                        f"Title: {job.get('title', 'N/A')}\n"
                        f"Company: {job.get('company_hint', 'Unknown')}\n"
                        f"Snippet: {job.get('snippet', '')[:300]}\n"
                        f"Source: {job.get('source', 'Web Search')}\n"
                        f"---"
                    )
                sub_jobs_input_str = "\n".join(sub_jobs_input_list)
                # Reuse the main prompt but swap in the sub-batch job list
                try:
                    sub_prompt = prompt.replace(jobs_input_str, sub_jobs_input_str)
                except Exception:
                    sub_prompt = None
                if not sub_prompt:
                    logger.error("Failed to construct sub-prompt. Defaulting to keep sub-batch.")
                    filtered_jobs.extend(sub_batch)
                    continue
                try:
                    response = ollama.chat(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a precise screening agent. Filter out irrelevant roles and locations. Output JSON matching the schema."},
                            {"role": "user", "content": sub_prompt}
                        ],
                        format=BatchFilterResponse.model_json_schema()
                    )
                    result = BatchFilterResponse.model_validate_json(response['message']['content'])
                    relevance_map = {eval_item.index: eval_item for eval_item in result.evaluations}
                    for idx, job in enumerate(sub_batch, 1):
                        eval_item = relevance_map.get(idx)
                        if eval_item:
                            if eval_item.is_relevant:
                                logger.info(f"✅ Kept: '{job.get('title')}' at '{job.get('company_hint', 'N/A')}' - Reason: {eval_item.reason}")
                                filtered_jobs.append(job)
                            else:
                                logger.info(f"❌ Skipped: '{job.get('title')}' at '{job.get('company_hint', 'N/A')}' - Reason: {eval_item.reason}")
                        else:
                            logger.warning(f"⚠️ Index {idx} not evaluated by Ollama in sub-batch. Defaulting to keep.")
                            filtered_jobs.append(job)
                except Exception as sub_err:
                    logger.error(f"Sub-batch failed: {sub_err}. Defaulting to keep sub-batch.")
                    filtered_jobs.extend(sub_batch)

    logger.info(f"Smart pre-filtering complete. Retained {len(filtered_jobs)} out of {len(job_list)} jobs.")
    return filtered_jobs

async def run_agent():
    # 1. Load configuration
    config = load_config()
        
    model_name = config.get("ollama_model", "deepseek-r1:1.5b")
    salary_threshold = config.get("target_compensation_threshold_lpa", 0)
    resumes_dir = config.get("resumes_dir", ".resumes")
    search_queries = config.get("search_queries", [])
    preferences_path = config.get("preferences_path", ".resumes/preferences.md")
    
    logger.info(f"Loaded config: Model={model_name}, Threshold={salary_threshold} LPA, Resumes={resumes_dir}")

    # Run cleanup of old directories (>30 days)
    clean_old_directories(data_dir="data", max_days=30)
    
    # Establish daily output directory
    today_str = datetime.date.today().isoformat()
    daily_dir = os.path.join("data", today_str)
    os.makedirs(daily_dir, exist_ok=True)
    jobs_json_path = os.path.join(daily_dir, "jobs.json")

    # Load all markdown files in resumes directory (including preferences.md)
    markdown_contents = []
    if os.path.exists(resumes_dir):
        for filename in os.listdir(resumes_dir):
            if filename.endswith(".md"):
                file_path = os.path.join(resumes_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        markdown_contents.append(f"=== Markdown File: {filename} ===\n{content}\n")
                    logger.info(f"Candidate preference/resume markdown file '{filename}' successfully loaded before starting.")
                except Exception as e:
                    logger.error(f"Error loading markdown file {filename}: {e}")
    preferences_text = "\n".join(markdown_contents)

    # Configure MCP Server Command
    python_exe = os.path.join(".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = "python"
        
    server_params = StdioServerParameters(
        command=python_exe,
        args=["mcp_server.py"]
    )
    
    logger.info(f"Connecting to MCP Server using {python_exe}...")
    
    # Connect to the MCP Server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            logger.info("MCP Session initialized successfully.")
            
            # Read resumes
            logger.info("Reading candidate resumes via MCP...")
            resumes_result = await session.call_tool("read_resumes", arguments={"directory": resumes_dir})
            resume_text = resumes_result.content[0].text
            
            if "No readable resume files" in resume_text or "does not exist" in resume_text:
                logger.warning("No candidate resume profile found. The agent will skip matching.")
                resume_text = ""
            else:
                logger.info("Candidate resume profile loaded.")

            # Run proactive config optimization
            config = await optimize_search_queries_and_config(
                resume_text=resume_text,
                preferences_text=preferences_text,
                config=config,
                model_name=model_name
            )
            # Re-read settings that might have been updated by optimization
            search_queries = config.get("search_queries", [])
            target_companies = config.get("target_companies", [])

            # Search for jobs and load direct URLs
            direct_urls = config.get("direct_job_urls", [])
            job_list = []

            async def schedule_filter_for_company(company_name, company_jobs_list):
                """Asynchronously filter a company's scraped jobs and persist partial results so dashboard can show them."""
                if not company_jobs_list:
                    return
                try:
                    filtered = await filter_jobs_batch_smart(company_jobs_list, resume_text, preferences_text, model_name)
                    # Normalize filtered job dicts to ensure dashboard fields exist
                    for fj in filtered:
                        if 'company' not in fj or not fj.get('company'):
                            fj['company'] = fj.get('company_hint', 'N/A')
                        if 'match_score' not in fj:
                            fj['match_score'] = fj.get('match_score', 0)
                        if 'ctc' not in fj:
                            fj['ctc'] = fj.get('ctc', 0.0)
                        if 'is_curve_ball' not in fj:
                            fj['is_curve_ball'] = fj.get('is_curve_ball', False)
                    job_list.extend(filtered)
                    # persist partial results for dashboard
                    try:
                        with open(jobs_json_path, 'w', encoding='utf-8') as jf:
                            json.dump(job_list, jf, indent=2)
                        logger.info(f"Partial results from {company_name} written to {jobs_json_path} ({len(filtered)} kept)")
                    except Exception as wf:
                        logger.error(f"Failed to write partial jobs.json: {wf}")
                except Exception as e:
                    logger.error(f"Async filter for company {company_name} failed: {e}")
            for url in direct_urls:
                job_list.append({"url": url, "title": "Direct Link", "snippet": "", "priority": 1})
            if direct_urls:
                logger.info(f"Loaded {len(direct_urls)} direct job URLs from config.")

            # Track completed companies for UI progress reporting
            completed_companies = []

            target_companies = config.get("target_companies", [])
            career_pages = config.get("company_career_pages", {})
            # Merge hardcoded career URLs from registry into config
            hardcoded_urls = get_career_url_map()
            for co_name, co_url in hardcoded_urls.items():
                if co_name not in career_pages:
                    career_pages[co_name] = co_url
            config["company_career_pages"] = career_pages
            restrict_to_target = config.get("restrict_to_target_companies", False)
            max_additional = config.get("max_additional_companies", 30)
            max_to_process = config.get("max_jobs_to_process", 25)
            career_max = config.get("career_scrape_max_per_company", 15)
            
            # Extract target base roles from search_queries
            base_roles = []
            for q in search_queries:
                q_lower = q.lower()
                if "site:" in q_lower or "reddit.com" in q_lower:
                    quoted = re.findall(r'\"([^\"]+)\"', q)
                    for r in quoted:
                        if r.strip() and r.strip() not in base_roles:
                            base_roles.append(r.strip())
                else:
                    if q.strip() and q.strip() not in base_roles:
                        base_roles.append(q.strip())
            
            if not base_roles:
                base_roles = ["data scientist", "quant developer", "software engineer"]
            
            logger.info(f"Extracted target base roles for company searches: {base_roles}")

            # Phase 0: Scrape hardcoded company career portals (highest priority)
            logger.info(f"Phase 0: Scraping hardcoded career portals for {target_companies}")
            role_kw_str = ", ".join(base_roles[:8])
            scraped_companies = set()
            for company in target_companies:
                update_scan_status(current_company=company, completed_companies=completed_companies)
                company_jobs = []
                try:
                    scrape_res = await session.call_tool(
                        "scrape_company_career_page",
                        arguments={
                            "company": company,
                            "role_keywords": role_kw_str,
                            "max_jobs": career_max,
                        },
                    )
                    scrape_text = scrape_res.content[0].text
                    if scrape_text.startswith("No hardcoded"):
                        logger.warning(scrape_text)
                        continue

                    scraped_companies.add(company.lower())
                    for block in re.split(r"Job \d+:", scrape_text):
                        if "URL:" not in block:
                            continue
                        url_m = re.search(r"URL:\s*(https?://\S+)", block)
                        title_m = re.search(r"Title:\s*(.*)", block)
                        loc_m = re.search(r"Location:\s*(.*)", block)
                        snippet_m = re.search(r"Snippet:\s*(.*)", block, re.DOTALL)
                        if url_m:
                            url = url_m.group(1).strip()
                            title = title_m.group(1).strip() if title_m else f"{company} Career Job"
                            snippet = snippet_m.group(1).strip() if snippet_m else ""
                            if loc_m:
                                snippet = f"Location: {loc_m.group(1).strip()}\n{snippet}"
                            if not any(j["url"] == url for j in job_list) and not any(j["url"] == url for j in company_jobs):
                                company_jobs.append({
                                    "url": url,
                                    "title": title,
                                    "snippet": snippet,
                                    "priority": 0,
                                    "company_hint": company,
                                })
                    logger.info(f"Career portal scrape for '{company}' complete.")
                except Exception as e:
                    logger.error(f"Career portal scrape failed for '{company}': {e}")
                finally:
                    completed_companies.append(company)
                    update_scan_status(current_company="", completed_companies=completed_companies)
                    # Schedule asynchronous filtering for this company's jobs so dashboard can update incrementally
                    asyncio.create_task(schedule_filter_for_company(company, company_jobs))

            # Phase 1: Search target companies
            logger.info(f"Gathering URLs for target companies: {target_companies}")
            for company in target_companies:
                if company.lower() in scraped_companies:
                    logger.info(f"Skipping Phase 1 web search queries for '{company}' because it was successfully scraped in Phase 0.")
                    continue
                update_scan_status(current_company=company, completed_companies=completed_companies)
                company_jobs = []
                # If cached career page exists, check it first
                if company in career_pages:
                    url = career_pages[company]
                    if not any(j["url"] == url for j in job_list) and not any(j["url"] == url for j in company_jobs):
                        company_jobs.append({"url": url, "title": f"{company} Portal", "snippet": "", "priority": 2})
                
                # Combine company with base target roles for direct company job searches (restricted to India or Remote)
                portal_queries = [
                    f"site:boards.greenhouse.io \"{company}\" \"India\" OR \"Remote\"",
                    f"site:lever.co \"{company}\" \"India\" OR \"Remote\"",
                    f"site:linkedin.com/jobs/view \"{company}\" \"India\" OR \"Remote\""
                ]
                for role in base_roles:
                    portal_queries.append(f"\"{company}\" \"{role}\" \"India\" OR \"Remote\"")
                
                for query in portal_queries:
                    logger.info(f"Searching for target company '{company}' jobs via query: '{query}'...")
                    try:
                        search_res = await session.call_tool("search_web", arguments={"query": query})
                        search_text = search_res.content[0].text
                        
                        blocks = re.split(r'Result \d+:', search_text)
                        for block in blocks:
                            if not block.strip():
                                continue
                            url_m = re.search(r'URL:\s*(https?://\S+)', block)
                            title_m = re.search(r'Title:\s*(.*)', block)
                            snippet_m = re.search(r'Snippet:\s*(.*)', block, re.DOTALL)
                            
                            if url_m:
                                url = url_m.group(1).strip()
                                title = title_m.group(1).strip() if title_m else f"{company} Job"
                                snippet = snippet_m.group(1).strip() if snippet_m else ""
                                
                                if not is_aggregator_list_page(url):
                                    if not any(j["url"] == url for j in job_list) and not any(j["url"] == url for j in company_jobs):
                                        company_jobs.append({"url": url, "title": title, "snippet": snippet, "priority": 2})
                    except Exception as e:
                        logger.error(f"Error searching for company '{company}' with query '{query}': {e}")
                
                if company not in completed_companies:
                    completed_companies.append(company)
                update_scan_status(current_company="", completed_companies=completed_companies)
                asyncio.create_task(schedule_filter_for_company(company, company_jobs))

            # Phase 2: If restriction is disabled, run general searches
            if not restrict_to_target:
                logger.info("Restriction is off. Running general search queries...")
                for query in search_queries:
                    search_query = query
                    if "site:" not in query.lower():
                        search_query = f"{query} job posting"
                        
                    logger.info(f"Searching general query: '{query}'...")
                    try:
                        search_res = await session.call_tool("search_web", arguments={"query": search_query})
                        search_text = search_res.content[0].text
                        
                        blocks = re.split(r'Result \d+:', search_text)
                        for block in blocks:
                            if not block.strip():
                                continue
                            url_m = re.search(r'URL:\s*(https?://\S+)', block)
                            title_m = re.search(r'Title:\s*(.*)', block)
                            snippet_m = re.search(r'Snippet:\s*(.*)', block, re.DOTALL)
                            
                            if url_m:
                                url = url_m.group(1).strip()
                                title = title_m.group(1).strip() if title_m else "General Job"
                                snippet = snippet_m.group(1).strip() if snippet_m else ""
                                
                                if not is_aggregator_list_page(url):
                                    if not any(j["url"] == url for j in job_list):
                                        job_list.append({"url": url, "title": title, "snippet": snippet, "priority": 3})
                    except Exception as e:
                        logger.error(f"Error searching general query '{query}': {e}")
            else:
                logger.info("Restriction is active. Skipping general search queries.")

            # Deduplicate and sort by priority (0: career scrape, 1: direct, 2: company search, 3: general)
            job_list.sort(key=lambda x: x["priority"])
            logger.info(f"Total compiled job list has {len(job_list)} entries.")

            # Smart batch pre-filtering of discovered jobs before fetching detail pages
            job_list = await filter_jobs_batch_smart(
                job_list=job_list,
                resume_text=resume_text,
                preferences_text=preferences_text,
                model_name=model_name
            )
            
            # Start processing loop
            processed_count = 0
            additional_companies = set()
            daily_jobs = []

            for idx, job in enumerate(job_list, 1):
                url = job["url"]
                title = job["title"]
                snippet = job["snippet"]
                priority = job["priority"]
                
                # Check limits
                if processed_count >= max_to_process:
                    logger.info(f"Processed maximum limit of {max_to_process} jobs. Stopping loop.")
                    break
                    
                logger.info(f"Processing [{idx}/{len(job_list)}]: {url} (Priority: {priority})")
                
                try:
                    res = await process_discovered_url(
                        url=url,
                        title=title,
                        snippet=snippet,
                        session=session,
                        config=config,
                        model_name=model_name,
                        salary_threshold=salary_threshold,
                        resume_text=resume_text,
                        preferences_text=preferences_text,
                        daily_dir=daily_dir,
                        company_hint=job.get("company_hint", ""),
                    )
                    
                    if res:
                        processed_count += 1
                        daily_jobs.append(res)
                        
                        # Auto-cache company career portal if it is one of the target companies
                        co_name = res.get("company", "").strip()
                        if co_name and co_name != "N/A" and co_name in target_companies:
                            career_pages = config.get("company_career_pages", {})
                            job_url = res.get("url", "")
                            base_portal_url = None
                            if "greenhouse.io" in job_url:
                                match = re.match(r'(https?://boards\.greenhouse\.io/[^/]+)', job_url)
                                if match:
                                    base_portal_url = match.group(1)
                            elif "lever.co" in job_url:
                                match = re.match(r'(https?://jobs\.lever\.co/[^/]+)', job_url)
                                if match:
                                    base_portal_url = match.group(1)
                            
                            if base_portal_url and co_name not in career_pages:
                                career_pages[co_name] = base_portal_url
                                config["company_career_pages"] = career_pages
                                # Save back to config.json
                                try:
                                    with open("config.json", "w", encoding="utf-8") as cf:
                                        json.dump(config, cf, indent=2)
                                    logger.info(f"Auto-cached portal URL for target company '{co_name}': {base_portal_url}")
                                except Exception as e:
                                    logger.error(f"Failed to auto-cache career portal for {co_name}: {e}")

                        # Track additional companies if it was a general search
                        if priority == 3 and co_name and co_name != "N/A" and co_name not in target_companies:
                            additional_companies.add(co_name)
                            if len(additional_companies) >= max_additional:
                                logger.info(f"Reached maximum limit of {max_additional} additional companies. Skipping remaining general jobs.")
                                # Remove any remaining priority 3 jobs from the list
                                job_list = [j for j in job_list if j["priority"] != 3]
                                
                except Exception as ollama_err:
                    logger.critical("Aborting job loop due to Ollama connection failure.")
                    break
            
            # Sort final JSON list by match score descending and rewrite
            if os.path.exists(jobs_json_path):
                try:
                    with open(jobs_json_path, "r", encoding="utf-8") as f:
                        final_jobs = json.load(f)
                    final_jobs.sort(key=lambda x: x.get("match_score", 0), reverse=True)
                    with open(jobs_json_path, "w", encoding="utf-8") as f:
                        json.dump(final_jobs, f, indent=2)
                    daily_jobs = final_jobs
                except Exception as e:
                    logger.error(f"Error sorting final jobs list: {e}")

            # Generate daily summary report using Ollama
            if daily_jobs:
                logger.info("Generating daily job hunting digest summary using Ollama...")
                jobs_summary_input = "\n".join([
                    f"- Job: {j.get('title','N/A')} at {j.get('company','N/A')} (CTC: {j.get('ctc',0.0)} LPA, Match Score: {j.get('match_score',0)}%, Curve Ball: {j.get('is_curve_ball',False)})"
                    for j in daily_jobs
                ])
                
                summary_prompt = f"""
                Analyze the following job hunt findings for today and write a brief, professional Markdown digest summary:
                
                {jobs_summary_input}
                
                Provide:
                1. Key Hiring Trends observed today (active roles, industries).
                2. Summary of top match opportunities.
                3. Highlight any surfaced 'Curve Ball' adjacent opportunities (if any).
                4. A concluding paragraph of recommendations for the candidate.
                
                Output ONLY valid Markdown. Do not include markdown code block ticks.
                """
                
                try:
                    sum_res = ollama.chat(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": "You are a professional career coach. Output ONLY valid Markdown summarizing the job search. No chat metadata."},
                            {"role": "user", "content": summary_prompt}
                        ]
                    )
                    summary_md = sum_res['message']['content'].strip()
                    
                    if summary_md.startswith("```markdown"):
                        summary_md = summary_md[11:]
                    if summary_md.startswith("```"):
                        summary_md = summary_md[3:]
                    if summary_md.endswith("```"):
                        summary_md = summary_md[:-3]
                    summary_md = summary_md.strip()
                    
                    summary_path = os.path.join(daily_dir, "summary.md")
                    with open(summary_path, "w", encoding="utf-8") as f:
                        f.write(summary_md)
                    logger.info(f"Saved daily summary to {summary_path}")
                except Exception as e:
                    logger.error(f"Error generating daily summary: {e}")
            else:
                summary_path = os.path.join(daily_dir, "summary.md")
                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write("# Daily Job Hunt Digest\n\nNo job listings met the criteria today. Try adjusting search queries or compensation thresholds in `config.json`.")
                logger.info("No jobs found today, saved default summary.")
                
            update_scan_status(current_company="", completed_companies=completed_companies, status="completed")

if __name__ == "__main__":
    asyncio.run(run_agent())
