# Project Rules & Coding Standards

## 🚀 The Sundar Pichai Standard (Architectural Excellence)
All agents working on this codebase must adhere to the highest standard of engineering, mimicking a senior developer with 10+ years of experience:
- **Zero Hardcoding**: Never hardcode values like locations, queries, or selectors unless absolutely unavoidable. Everything must be generic, configuration-driven, and dynamically determined to support sharing this product with other users who have different resumes, preferences, and locations.
- **Robust and Scalable Architecture**: Write modular, clean, and highly readable code with proper error handling and logging.
- **Defensive Design**: Guard against failures in external systems (like bot protection on ATS portals, LLM response formatting anomalies, or network timeouts).

## 📝 Continuous Documentation Update
After every major change or feature implementation:
- You **MUST** update [README.md](file:///c:/Users/paart/OneDrive/Desktop/job-hunter-agent/README.md) to document the new user-facing functionality and setup steps.
- You **MUST** update [claude.md](file:///c:/Users/paart/OneDrive/Desktop/job-hunter-agent/claude.md) to log developer notes, model expectations, configurations, and backend flow adjustments.
- Maintain document integrity by preserving surrounding contexts and avoiding truncation.
