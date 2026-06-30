# 🕵️‍♂️ Job Hunter Agent & Dashboard

Welcome to the **Job Hunter Agent & Dashboard**, a semi-automated job search assistant. This system scans target company career portals and web searches for roles (such as Data Science, Quantitative Research, and Software Engineering), analyzes job descriptions using a local LLM via Ollama, matches them against your resume/preferences, and presents them in an interactive web dashboard.

---

## 🌟 Key Features

1. **Web Dashboard**: An interactive, single-page UI to view daily jobs, check match evaluations, view trend insights, configure target companies/search queries, and start/stop scans or the scheduler. Features a dual-tab experience:
   - **Latest Run**: Shows jobs discovered during the most recent scan.
   - **All Open Jobs (Verified)**: Shows a persistent history of all discovered jobs that have been active and verified to be still open.
2. **Local LLM Intelligence (Ollama)**: Automatically extracts structured job details (title, company, required skills, location, estimated salary).
3. **Semantic Relevancy Scoring**: Fully leverages the LLM to understand your resume context and assigns a semantic 0-100% match score (unlike rigid keyword-matching scripts), allowing the UI to perfectly arrange your best fits at the top!
4. **Intelligent Data Cleaning**: LLM automatically cleans up and summarizes noisy scraped job titles into concise 2-5 word roles so your dashboard looks incredibly clean.
5. **Advanced Web Scraping (MCP Server)**: Uses a Model Context Protocol (MCP) server running Playwright Chromium to navigate direct ATS boards (Lever, Greenhouse, Workday, Eightfold, etc.).
4. **LLM-Driven Job Discovery**: Instead of brittle regex, the agent uses an AI web navigator to scan company career portals, intelligently identifying and extracting actual job posting links.
5. **Strict URL Validation**: Prevents scraping random news articles or blogs by enforcing a strict URL bouncer that only permits valid ATS domains (e.g. greenhouse.io, lever.co) or strictly formatted career job paths.
6. **Job Availability Verification**: At the start of each scan, the agent automatically validates all previously discovered jobs by pinging their URLs. Closed jobs (yielding 404s or containing "no longer accepting applications" messages) are automatically pruned from the persistent database.
7. **Dynamic Feedback Loop**: When you rate a job (Thumbs Up/Down) on the dashboard, the system uses Ollama to dynamically update your preferences profile in `resumes/preferences.md`.
8. **Robust Data Formats**: Outputs parsed jobs into daily folders (`data/YYYY-MM-DD/`) in both JSON (`jobs.json`) and Excel (`jobs.xlsx`) formats, alongside a markdown summary. A unified verified open list is stored in `data/all_jobs.json`.
9. **Company Master Database**: Manage known ATS configurations via a persistent UI dropdown. Companies are stored in a master database (`data/companies_db.json`), meaning removing them from active tracking does not delete their configuration entirely.

---

## 📂 Architecture Overview

* **`app.py`**: The FastAPI backend server. Serves the static dashboard, provides JSON REST endpoints, and manages background subprocesses for scans and scheduling.
* **`job_agent.py`**: The orchestrator of the job hunting process. Starts the MCP client, triggers searches, retrieves resumes, calls Ollama to extract and score roles, gates them by salary threshold, and compiles the daily reports.
* **`mcp_server.py`**: The FastMCP server containing core tools (`search_web`, `fetch_web_page`, `scrape_company_career_page`, `read_resumes`) called by the agent.
* **`scheduler.py`**: A periodic scanner script that runs `job_agent.py` at a configurable interval (e.g., every 12 hours) to auto-check career boards.
* **`career_scraper.py` & `career_pages.py`**: Houses the selectors, navigation workflows, and instructions for scraping specific company portals.
* **`templates/index.html`**: The frontend UI for the web dashboard.
* **`config.json`**: App configuration containing your target compensation threshold, currency, target location, search queries, target companies, and portal registry.

---

## 🛠️ Prerequisites

Before getting started, make sure you have:
1. **Python 3.10+** installed on your system.
2. **Ollama** installed and running locally.
3. **Google Chrome** or chromium-based browser (Playwright will download its own instance).

---

## 🚀 Setup & Installation

### 1. Initialize Virtual Environment
Open PowerShell or your command prompt in the project root directory and run:
```powershell
python -m venv venv
```

### 2. Activate Virtual Environment
* **PowerShell**:
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
* **Command Prompt**:
  ```cmd
  .\.venv\Scripts\activate.bat
  ```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Install Playwright Browsers
To install the headless Chromium browser used for web search and page fetching:
```powershell
playwright install
```

### 5. Setup Local LLM (Ollama or Claude)
1. Start your local LLM server (Ollama: `ollama serve`, or your Claude/other LLM per vendor instructions).
2. For Ollama, download the model configured in `config.json` (defaults to `deepseek-r1:1.5b`):
   ```powershell
   ollama pull deepseek-r1:1.5b
   ```
3. For Claude or other LLMs, see `claude.md` for integration notes (model name, endpoint, auth, and minimal request/response expectations). Configure `config.json` to point to your model and endpoint.
- **Cross-Platform Compatibility:** Easily configurable settings in `config.json` to adapt to various target companies, roles, and locations.
- **Robust Extraction Pipeline:** Resilient extraction logic with automatic fallback context preservation, handling 15k-character large job postings seamlessly.

## Getting Started: Add Resumes & Profiles
1. Create a `resumes/` folder in the project root if it does not exist.
2. Place your resume file(s) inside (supported formats: `.pdf`, `.txt`, `.md`).
3. (Optional) Create a initial `resumes/preferences.md` file. If left blank, rating jobs in the dashboard UI will automatically construct this file.

---

## 🖥️ How to Launch & Run Everything

There are several ways to run and interact with the system:

### A. Run the Web Dashboard (Recommended)
This starts the FastAPI server which serves the web dashboard UI at `http://127.0.0.1:8000`.

Start the dashboard application:
```bash
python app.py
```
> **Note:** The application will automatically check if `ollama serve` is running. If it isn't, it will silently launch it in the background with optimized GPU environment variables (`OLLAMA_KEEP_ALIVE=24h`). You do not need to run `ollama serve` manually anymore!

1. Open **`http://127.0.0.1:8000`** in your browser.
2. From the dashboard UI, you can:
   * **Trigger Scan**: Initiates a background scan process immediately.
   * **Start/Stop Scheduler**: Starts the periodic background scanner (runs according to `scan_interval_hours` in your config).
   * **Configure**: View and modify target companies, search queries, and toggle company restrictions.
   * **Review & Rate**: Rate job listings to refine your profile.

---

### B. Run the Job Scan Manually (CLI)
If you want to run the job search agent directly from the command line without opening the web dashboard:
```powershell
python job_agent.py
```
This runs the full scraping and LLM-matching sequence. The output will be written incrementally to `data/YYYY-MM-DD/jobs.json` and `data/YYYY-MM-DD/jobs.xlsx`.

---

### C. Run the Periodic Scheduler (CLI)
To run the interval-based scanner in the background via command line:
```powershell
python scheduler.py
```
It reads `scan_interval_hours` from `config.json` and runs `job_agent.py` repeatedly at that interval.

---

### D. Standalone MCP Server (Advanced)
If you wish to host the tools of the agent to be consumed by other MCP clients (like Claude Desktop or another agent framework):
```powershell
python mcp_server.py
```
This launches the tool server listening over `stdio` transport.

---

## ⚙️ Configuration Details (`config.json`)

Key settings in `config.json` include:
* `"ollama_model"`: The local model used for NLP tasks (`deepseek-r1:1.5b`, `llama3`, etc.).
* `"smart_filter_batch_size"`: Number of job listings sent per LLM batch (default: 5). Lower this to avoid model context-size errors (exceed_context_size).
* `"smart_filter_fallback_size"`: Sub-batch size used when retrying failed batches (default: 5). The agent will attempt smaller sub-batches on LLM failures.
* `"resume_max_chars_in_prompt"`: Max characters of resume/profile included in the LLM prompt (default: 1000).
* `"target_compensation_threshold"`: Minimum annual salary threshold to output a job. Jobs estimated under this are skipped.
* `"currency"`: The local currency for salary calculations (e.g. "USD", "INR").
* `"target_location"`: Target geographic location (e.g. "Remote", "India", "US").
* `"disliked_companies"`: List of strings for companies to actively avoid filtering.
* `"restrict_to_target_companies"`: If `true`, the search agent only scrapes target companies listed in `target_companies`. If `false`, general search queries are run as well.
* `"target_companies"`: Array of company names to target.
* `"search_queries"`: Search query templates containing search modifiers (e.g. `site:linkedin.com/jobs/view`).
* `"scan_interval_hours"`: The interval hours between periodic scans.

---

## 🔍 Troubleshooting

*   **Ollama GPU Watchdog Timeout / Crashes**
    *   **Symptom:** `llama-server GPU discovery watchdog timed out` or the LLM evaluation gets stuck at "Pending".
    *   **Why it Happens:** Windows hybrid graphics sometimes puts the discrete GPU to sleep, or the VRAM gets completely saturated.
    *   **Solution (Automated):** The application now automatically manages Ollama execution. It restricts the context window (`num_ctx: 4096`) and sets `OLLAMA_KEEP_ALIVE=24h` to prevent thrashing GPU memory. It also uses asynchronous fallbacks to gracefully timeout without freezing the dashboard.
    *   **Workaround (Run on CPU only):** If you still face hardware crashes despite the new optimizations, you can bypass the GPU entirely. Open `app.py` and manually set `env["CUDA_VISIBLE_DEVICES"] = ""` in the `startup_event()` function. This completely bypasses GPU discovery timeouts and runs model inference safely and reliably on the CPU.
*   **Ollama Connection Error**: Ensure the Ollama server is running (usually at `http://localhost:11434`). Try opening that URL in your browser or checking the Ollama app tray.
*   **Playwright/Browser Issues**: If scraping fails due to browser launching issues, make sure you ran `playwright install`.
*   **FastAPI Server Already in Use**: If port 8000 is occupied, you can change the port in the main block of `app.py`:
    ```python
    uvicorn.run("app:app", host="127.0.0.1", port=8080, reload=True)
    ```
