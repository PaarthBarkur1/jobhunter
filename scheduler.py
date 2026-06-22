"""
Runs job_agent.py on a regular interval so company career pages are checked automatically.
"""

import os
import sys
import time
import json
import logging
import subprocess
import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("job_scheduler")


def load_interval_hours() -> float:
    default = 12.0
    if not os.path.exists("config.json"):
        return default
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        return float(config.get("scan_interval_hours", default))
    except Exception as e:
        logger.error(f"Failed to read scan_interval_hours: {e}")
        return default


def run_scan():
    python_exe = os.path.join(".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable
    logger.info("Starting scheduled job_agent scan...")
    result = subprocess.run([python_exe, "job_agent.py"], capture_output=False)
    if result.returncode == 0:
        logger.info("Scheduled scan completed successfully.")
    else:
        logger.error(f"Scheduled scan failed with exit code {result.returncode}")


def main():
    interval_hours = load_interval_hours()
    interval_seconds = max(interval_hours * 3600, 3600)  # minimum 1 hour
    logger.info(f"Job scheduler started. Interval: every {interval_hours} hours ({interval_seconds}s).")

    while True:
        started = datetime.datetime.now().isoformat(timespec="seconds")
        logger.info(f"=== Scan cycle started at {started} ===")
        try:
            run_scan()
        except Exception as e:
            logger.error(f"Scan cycle error: {e}")
        logger.info(f"Next scan in {interval_hours} hours.")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
