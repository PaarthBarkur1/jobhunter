deepseek.md

Purpose

This file explains expectations and integration notes for using Deepseek (recommended) as the local LLM for the Job Hunter Agent.

What the model will see

- Prompts include a short candidate resume summary, candidate preferences, and a small batch of job listings (title, company, short snippet).
- The agent intentionally trims resume content and limits batch sizes to avoid exceeding model context windows.

Recommended model

- Ollama model: `deepseek-r1:1.5b` (pull with `ollama pull deepseek-r1:1.5b`).

Important behaviors

- Chunking: The agent sends `smart_filter_batch_size` jobs per request (configurable; default: 5). On failures it retries with `smart_filter_fallback_size` sub-batches.
- Resume trimming: `resume_max_chars_in_prompt` controls resume length included in prompts (default: 1000 chars).
- Output format: The model must return strictly structured JSON matching the project's schema for filtering/evaluation.

Quick test

1. Ensure Ollama is running and model is pulled:
   ollama pull deepseek-r1:1.5b
   ollama serve

2. Adjust config.json if desired (e.g., `"smart_filter_batch_size": 5`).

3. Run a single scan to exercise the LLM pre-filter:
   python job_agent.py

If the agent logs no exceed_context_size errors and produces `data/YYYY-MM-DD/jobs.json`, chunking is working.
