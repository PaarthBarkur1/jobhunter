import os
import re
import json
import logging
from typing import List, Optional
from pydantic import BaseModel, Field
import ollama

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("test_pipeline")

# ==========================================
# PYDANTIC SCHEMAS (Matches job_agent.py)
# ==========================================
class JobDetails(BaseModel):
    is_job_posting: bool = Field(description="True if the text is a specific job posting/description, False if it is a general page, list, or error.")
    title: str = Field(description="The formal job title or role, or 'N/A' if not a job posting")
    company: str = Field(description="The name of the hiring organization or company, or 'N/A'")
    required_skills: List[str] = Field(default=[], description="Core technical or domain skills listed. Empty list if none.")
    experience_level: str = Field(description="Required minimum years of experience or seniority level, or 'N/A'")
    explicit_salary: Optional[str] = Field(None, description="Explicit salary stated in text, e.g. '30 LPA', '₹20,00,000', '$120,000'")
    posted_date: Optional[str] = Field(None, description="The date the job was posted, if explicitly stated or inferred from text, e.g. '2026-05-10', '3 days ago', 'October 2025', or 'Unknown'.")

class SalaryEstimation(BaseModel):
    estimated_salary: float = Field(description="The estimated average/median annual salary. If not found, return 0.0.")
    reason: str = Field(description="Brief reason or source snippet for the estimation")

class JobMatchEvaluation(BaseModel):
    score: int = Field(description="Match score between 0 and 100 representing how well candidate profile matches the job requirements.")
    reason: str = Field(description="A brief 1-2 sentence explanation of the rating.")

# Import salary parsing utility from job_agent
from job_agent import parse_salary_to_target_currency

# ==========================================
# MOCK WEB DATA
# ==========================================
MOCK_JOB_POSTING = """
Careers at GreenTech Solutions Inc.
Job Position: Remote Senior Python Developer (Quant & Machine Learning focus)

About Us:
GreenTech is a leading options hedging and energy optimization company. We use mathematical optimization models to reduce carbon footprints.

Requirements:
- Strong Python programming (3+ years experience)
- Experience with Mathematical Optimization, Quantitative Modeling, and Option Hedging (Black-Scholes is a plus)
- Familiarity with LLM frameworks, RAG architectures, and multi-agent systems
- Background in Electronics, Data Science, or related quantitative fields

Compensation:
We offer a highly competitive package of 32 LPA (Lakhs Per Annum) in India, or equivalent in other regions.

Apply by sending your resume to jobs@greentech.example.com.
"""

def test_pipeline():
    logger.info("Starting local pipeline integration test...")
    
    # 1. Load config
    config_path = "config.json"
    with open(config_path, "r") as f:
        config = json.load(f)
        
    model_name = config.get("ollama_model", "llama3.2:latest")
    salary_threshold = config.get("target_compensation_threshold", 0)
    
    logger.info("=" * 60)
    logger.info(f"Test Configuration: Model={model_name}, Threshold={salary_threshold}")
    
    # 2. Read resume
    resume_text = ""
    resumes_dir = ".resumes"
    import glob
    from pypdf import PdfReader
    files = glob.glob(os.path.join(resumes_dir, "*"))
    for file_path in files:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".txt", ".md"]:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    resume_text += f.read() + "\n"
            except Exception:
                pass
        elif ext == ".pdf":
            try:
                reader = PdfReader(file_path)
                pdf_text = []
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        pdf_text.append(text)
                resume_text += "\n".join(pdf_text) + "\n"
            except Exception:
                pass
    if not resume_text:
        logger.error("No candidate resume profile found for test!")
        return
    logger.info("Loaded candidate resume successfully.")
    
    # 3. Parse job posting using Ollama
    logger.info("Step 1: Extracting job details from mock posting via Ollama...")
    extract_prompt = f"Analyze the following scraped webpage text and extract structured job details if it is a job description:\n\n{MOCK_JOB_POSTING}"
    
    try:
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a precise job data miner. Parse the text and output EXACTLY a JSON structure matching the schema. If the text does not contain a job posting, mark is_job_posting as false."},
                {"role": "user", "content": extract_prompt}
            ],
            format=JobDetails.model_json_schema()
        )
        job_metrics = JobDetails.model_validate_json(response['message']['content'])
    except Exception as e:
        logger.error(f"Ollama job extraction failed: {e}")
        return

    logger.info(f"Ollama extracted: is_job_posting={job_metrics.is_job_posting}, Title='{job_metrics.title}', Company='{job_metrics.company}'")
    logger.info(f"Explicit Salary extracted: '{job_metrics.explicit_salary}'")
    logger.info(f"Required Skills extracted: {job_metrics.required_skills}")

    # 4. Gatekeeper check
    logger.info("Step 2: Checking compensation threshold...")
    estimated_pay = 0.0
    if job_metrics.explicit_salary:
        estimated_pay = parse_salary_to_target_currency(job_metrics.explicit_salary, config.get('currency', 'USD'))
    logger.info(f"Calculated pay: ~{estimated_pay} {config.get('currency', 'USD')}")
    
    if estimated_pay > 0 and estimated_pay < salary_threshold:
        logger.warning(f"Gated: estimated pay {estimated_pay} is below threshold {salary_threshold}.")
        return None
    elif estimated_pay > 0:
        logger.info(f"Passed Gatekeeper check! {estimated_pay} >= {salary_threshold}.")
        
    # 5. Score candidate resume alignment
    logger.info("Step 3: Evaluating resume alignment using Ollama...")
    match_prompt = f"""
    Evaluate structural alignment between Candidate Resumes and the Target Job details.
    
    Candidate Resumes:
    {resume_text}
    
    Target Job:
    - Title: {job_metrics.title}
    - Company: {job_metrics.company}
    - Skills: {', '.join(job_metrics.required_skills)}
    - Experience/Seniority: {job_metrics.experience_level}
    """
    
    try:
        match_res = ollama.chat(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a professional hiring manager. Evaluate the resume match and return a score (0 to 100) and reason in JSON schema format."},
                {"role": "user", "content": match_prompt}
            ],
            format=JobMatchEvaluation.model_json_schema()
        )
        match_data = JobMatchEvaluation.model_validate_json(match_res['message']['content'])
        logger.info(f"Candidate Match Score: {match_data.score}% - Reason: {match_data.reason}")
    except Exception as e:
        logger.error(f"Ollama match scoring failed: {e}")
        return

    # 6. Log to test digest
    if match_data.score >= 80:
        logger.info(f"🚀 Strong Match identified ({match_data.score}%)! Logging to {digest_path}")
        with open(digest_path, "w", encoding="utf-8") as f:
            f.write("# Job Hunting Daily Digest (TEST)\n\n")
            f.write(f"## [{job_metrics.title} - {job_metrics.company}](https://example.com/mock-post)\n")
            f.write(f"- **Estimated Salary:** {estimated_pay} {config.get('currency', 'USD')}\n")
            f.write(f"- **Profile Match Score:** {match_data.score}%\n")
            f.write(f"- **Reasoning:** {match_data.reason}\n")
            f.write(f"- **Required Skills:** {', '.join(job_metrics.required_skills)}\n")
            f.write(f"- **Experience Level:** {job_metrics.experience_level}\n\n")
        logger.info(f"Written mock digest summary to {digest_path}")
    else:
        logger.warning(f"Match score {match_data.score}% is below threshold 80%. Not logged.")

if __name__ == "__main__":
    test_pipeline()
