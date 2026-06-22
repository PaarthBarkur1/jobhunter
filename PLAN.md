# Job Hunter Agent — Improvement Plan

Goals
- Improve performance and reliability without hardcoding values.
- Keep changes generic and reusable across modules.

Planned actions
1. Introduce a shared HTTP client with connection pooling and retries (`http_client.py`).
2. Add a lightweight in-memory layer for the file cache (`cache.py`) to reduce filesystem I/O.
3. Route all ad-hoc `requests` calls through the shared client (update `career_scraper.py`, `mcp_server.py`).
4. Identify heavy modules (scrapers, Playwright usage) and propose further async/batching improvements.
5. Add basic benchmarks and tests for critical paths (scrape and fetch functions).
6. Keep configuration generic via `config.json` (already present) and avoid hardcoded timeouts.

Notes
- The changes are minimal, low-risk, and generic (session pooling, retry, in-memory cache).
- Next steps: run unit/functional tests and profile long-running workflows to find further gains.
