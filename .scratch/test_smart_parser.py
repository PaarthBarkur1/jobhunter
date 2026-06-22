import os
import sys
import json
import asyncio
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("test_smart_parser")

# Ensure workspace root is in path to import modules
sys.path.append(r"c:\Users\paart\OneDrive\Desktop\job-hunter-agent")

from job_agent import (
    optimize_search_queries_and_config,
    filter_jobs_batch_smart,
    load_config,
    is_posted_over_6_months_ago
)

async def test_smart_parser():
    logger.info("Initializing Smart Parser Integration Test...")
    
    # 1. Load config
    config = load_config()
    model_name = config.get("ollama_model", "deepseek-r1:1.5b")
    resumes_dir = r"c:\Users\paart\OneDrive\Desktop\job-hunter-agent\.resumes"
    
    logger.info(f"Using Ollama Model: {model_name}")
    
    # 2. Load resumes & preferences
    resume_text = ""
    preferences_text = ""
    
    if os.path.exists(resumes_dir):
        for filename in os.listdir(resumes_dir):
            file_path = os.path.join(resumes_dir, filename)
            if filename.endswith(".md"):
                with open(file_path, "r", encoding="utf-8") as f:
                    preferences_text += f.read() + "\n"
            elif filename.endswith(".txt") or filename.endswith(".pdf"):
                # Simulating resume text
                resume_text += f"Candidate resume info from {filename}\n"
    
    if not preferences_text:
        # Fallback dummy preferences if none exist
        preferences_text = """
        # Job Preferences Profile
        ## Likes
        - Quantitative Researcher
        - Machine Learning Engineer in Bengaluru
        ## Dislikes
        - Trading firm culture (Millennium Management)
        - Service companies like Infosys or TCS
        - Non-technical roles
        - Positions based in the US without remote options
        """
        
    if not resume_text:
        resume_text = """
        Name: Paarth Barkur
        Role: Quant / FinDS / Data Scientist
        Skills: Python, Machine Learning, RAG, Options Hedging, Quantitative Finance
        Experience: 2 years experience in quantitative analyst or scientist roles.
        """

    # 3. Test Config Optimization
    logger.info("--- Testing Config Optimization ---")
    optimized_config = await optimize_search_queries_and_config(
        resume_text=resume_text,
        preferences_text=preferences_text,
        config=config.copy(),
        model_name=model_name
    )
    
    logger.info(f"Optimized Search Queries: {optimized_config.get('search_queries')}")
    logger.info(f"Optimized Target Companies: {optimized_config.get('target_companies')}")
    
    # 4. Test Batch Pre-Filtering
    logger.info("--- Testing Batch Job Pre-Filtering ---")
    mock_jobs = [
        {
            "title": "Quantitative Researcher - Commodities",
            "company_hint": "Jane Street",
            "snippet": "Join our commodities research team in Bengaluru. Experience with Python, Black-Scholes, and data science is required.",
            "source": "Career Portal",
            "url": "https://www.janestreet.com/careers/qr-commodities"
        },
        {
            "title": "Systems Analyst (Operations)",
            "company_hint": "Millennium Management",
            "snippet": "We are seeking a senior operations systems analyst for our trading infrastructure. Millennium Management environment.",
            "source": "Web Search",
            "url": "https://careers.mlp.com/jobs/ops-systems-analyst"
        },
        {
            "title": "Software Engineer (PHP & Java)",
            "company_hint": "Infosys",
            "snippet": "Infosys is looking for a software engineer to support legacy banking applications. Location: Pune, onsite.",
            "source": "Web Search",
            "url": "https://careers.infosys.com/jobs/se-php"
        },
        {
            "title": "Lead Machine Learning Scientist",
            "company_hint": "Google",
            "snippet": "Lead team in developing state of the art generative AI models and RAG systems. Location: Remote (India).",
            "source": "Career Portal",
            "url": "https://google.com/jobs/ml-scientist"
        },
        {
            "title": "Senior Trader (NYC)",
            "company_hint": "Jane Street",
            "snippet": "Experienced trader needed for NYC options market. Candidate must reside and work onsite in New York City, US.",
            "source": "Career Portal",
            "url": "https://janestreet.com/jobs/options-trader-nyc"
        }
    ]
    
    filtered = await filter_jobs_batch_smart(
        job_list=mock_jobs,
        resume_text=resume_text,
        preferences_text=preferences_text,
        model_name=model_name
    )
    
    logger.info("=== Test Results Summary ===")
    logger.info(f"Original Mock Jobs Count: {len(mock_jobs)}")
    logger.info(f"Filtered Jobs Count: {len(filtered)}")
    
    retained_titles = [j.get("title") for j in filtered]
    logger.info(f"Retained Job Titles: {retained_titles}")
    
    # Assertions / Validations
    assert any("Commodities" in title for title in retained_titles), "Should have kept Jane Street Commodities QR"
    assert any("Machine Learning Scientist" in title for title in retained_titles), "Should have kept Google ML Scientist (Remote India)"
    assert not any("Millennium" in title for title in retained_titles), "Should have filtered out Millennium"
    assert not any("Infosys" in title for title in retained_titles), "Should have filtered out Infosys"
    assert not any("NYC" in title for title in retained_titles), "Should have filtered out US onsite roles"
    
    # 5. Test Date Filter Utility
    logger.info("--- Testing Date Filtering Utility ---")
    assert is_posted_over_6_months_ago("2 years ago") is True, "Should identify 2 years ago as older than 6 months"
    assert is_posted_over_6_months_ago("8 months ago") is True, "Should identify 8 months ago as older than 6 months"
    assert is_posted_over_6_months_ago("1 year ago") is True, "Should identify 1 year ago as older than 6 months"
    assert is_posted_over_6_months_ago("2 weeks ago") is False, "Should identify 2 weeks ago as within 6 months"
    assert is_posted_over_6_months_ago("3 days ago") is False, "Should identify 3 days ago as within 6 months"
    assert is_posted_over_6_months_ago("today") is False, "Should identify today as within 6 months"
    assert is_posted_over_6_months_ago("2024-05-10") is True, "Should identify May 2024 as older than 6 months"
    assert is_posted_over_6_months_ago("2026-05-15") is False, "Should identify May 2026 as within 6 months"
    
    logger.info("🎉 Integration test passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_smart_parser())
