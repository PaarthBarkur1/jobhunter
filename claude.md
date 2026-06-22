claude.md

Purpose

This file explains what a new LLM instance (e.g., Claude, a cloud LLM, or any local model) should expect and how it will be used by the Job Hunter Agent.

What the model will see

- config.json: contains model name/endpoint and integration settings.
- resumes/: user resumes and `resumes/preferences.md` (profile used to score/match jobs).
- job text payloads: job descriptions scraped by the MCP server and passed to the LLM for extraction and scoring.

Required capabilities

- Accept text job descriptions and return structured JSON (title, company, skills, location, est_salary).
- Score or rank a job vs. a resume/profile (0–100) and provide brief rationale.
- Be invokable over HTTP or via a local client library (the project supports calling a local LLM endpoint).

How the project invokes the LLM

- job_agent.py calls the configured model (per config.json) to parse and score jobs.
- mcp_server.py exposes scraping/fetching tools; job_agent orchestrates the flow: scrape -> LLM -> filter -> write data.

Configuration hints

- Set model/provider in config.json (e.g. "ollama_model" or "llm_provider"/"llm_endpoint").
- If using a cloud LLM, ensure credentials or API keys are available in env vars and referenced by the app.
- Ensure the LLM returns JSON that matches the project's expectations (keys: title, company, skills, location, estimated_salary, score, summary).

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
