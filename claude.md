claude.md

Purpose

This file explains what a new LLM instance (e.g., Claude, a cloud LLM, or any local model) should expect and how it will be used by the Job Hunter Agent.

What the model will see

- config.json: contains model name/endpoint and integration settings.
- resumes/: user resumes and `resumes/preferences.md` (profile used to score/match jobs).
- data/all_jobs.json: unified database tracking all verified persistent open jobs.
- job text payloads: job descriptions scraped by the MCP server and passed to the LLM for extraction and scoring.

Required capabilities

- Accept text job descriptions and return structured JSON (title, company, skills, location, est_salary).
- Score or rank a job vs. a resume/profile (0–100) and provide brief rationale.
- Be invokable over HTTP or via a local client library (the project supports calling a local LLM endpoint).

How the project invokes the LLM

- job_agent.py calls the configured model (per config.json) to parse and score jobs.
- mcp_server.py exposes scraping/fetching tools; job_agent orchestrates the flow: scrape -> LLM -> filter -> write data.

URL Validation, Database, and Scraping Flow

- The system now uses a Master Database approach (`data/companies_db.json`) for persistence, ensuring UI deletions do not erase known ATS configs.
- The scraper no longer uses generalized web searching (e.g., Bing/Google) to avoid hallucinated links and aggregators. It strictly navigates the direct career portals of target companies.
- To discover jobs, the system uses an LLM-driven Web Navigator (`_extract_jobs_with_llm` in `career_scraper.py`), passing raw links from the career portal to the LLM to intelligently extract genuine job postings.
- The URL bouncer (`is_valid_job_post` in `job_agent.py`) acts as a fallback to ensure only true ATS domains (e.g. greenhouse.io, lever.co, eightfold.ai) and structured paths (e.g., /jobs/\d+) enter the pipeline.
- The crawler dynamically modifies search filters based on `target_location` directly, without using hardcoded logic, guaranteeing generic extensibility.

Configuration hints

- Set model/provider in config.json (e.g. "ollama_model" or "llm_provider"/"llm_endpoint").
- If using a cloud LLM, ensure credentials or API keys are available in env vars and referenced by the app.
- Ensure the LLM returns JSON that matches the project's expectations (keys: title, company, skills, location, explicit_salary, etc).
- The LLM should respect the configured `target_location`, `currency`, and `disliked_companies` provided in `config.json`.
- **Concurrency Options**: Configurable `max_concurrent_companies` allows scaling while avoiding API limits.

### Jun 29, 2026 Updates
- Fixed ATS data loss by increasing web page text fetch size from 4000 to 15000 characters to prevent early truncation.
- Increased Ollama LLM extraction prompt window size (`MAX_JOB_CHARS`) from 1500 to 12000.
- Implemented heuristic title cleaning and `company_hint` fallback to address missing fields in smaller 1.5B model architectures.
- Verified robust operation against companies like Microsoft and Uber.

- Do not make assumptions about currency or location unless explicitly stated.

Quick test commands

1. Start the LLM server (Ollama or your Claude endpoint).
2. From project root (with venv active), run a single scan to exercise LLM calls:
   ```powershell
   python job_agent.py
   ```
   - Output is written to data/YYYY-MM-DD/jobs.json and jobs.xlsx.
3. Or run the dashboard (end-to-end test):
   ```powershell
   python app.py
   ```
   - Open http://127.0.0.1:8000 and trigger a scan from the UI.

If the LLM is reachable and responds with structured extraction and scores, the job_agent run will complete and produce output files in data/.

Troubleshooting

- If the LLM returns text instead of JSON, wrap or adjust prompts to request strict JSON output.
- For Claude cloud, ensure rate limits and payload sizes are within provider limits.
- If parsing fails, inspect logs printed by job_agent.py for the exact LLM response and adjust prompt templates.


## Refactoring Note (June 2026)
- Removed Python regex override for job match_score calculation. The 1.5B model is now instructed to generate a semantic score from 0-100 directly. This vastly improves relevancy tracking and sorting.
- Instructed the LLM to aggressively truncate and clean job titles (max 5 words) to avoid huge scraped descriptions leaking into the title field.
- Configured `.gitignore` to prevent tracking daily job output runs (e.g. `data/YYYY-MM-DD/`), local screenshots (`uber_screenshot.png`), temporary/test files (`test_uber.py`, `uber_test.html`), and `.scratch/` directories.
- Retained tracking of the master database configuration (`data/companies_db.json`) while ignoring the rest of the dynamic files under `data/`.

## July 2026 Refactoring Updates (SQLite & Decoupled Services)
- **State Management**: Replaced JSON state management (`data/all_jobs.json`, `data/YYYY-MM-DD/`) with a robust SQLite database (`data/jobs.db`). Models are defined in `core/models.py` (JobPosting, Company, ScanLog) using async SQLAlchemy.
- **Architecture**: Transitioned from the monolithic `job_agent.py` and `mcp_server.py` to a decoupled, modular architecture with specialized services: `services/scraper_service.py`, `services/llm_service.py`, and `services/evaluator_service.py`.
- **Concurrency Isolation**: I/O tasks use Semaphores for concurrent web fetching while LLM tasks are strictly queued with concurrency limit 1 in `llm_service.py` to prevent VRAM OOM errors.
- **Orchestration**: The pipeline is now managed via an async DAG workflow in `workers/orchestrator.py` which delegates to the services (Discovery -> Deduplication -> Extraction/Evaluation -> Persistence).
