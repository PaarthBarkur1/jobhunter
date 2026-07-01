import logging
from typing import Dict, Any
from .llm_service import LLMService

logger = logging.getLogger(__name__)

class EvaluatorService:
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service
        
        # Define strict JSON schema for the evaluation output
        self.evaluation_schema = {
            "type": "object",
            "properties": {
                "job_title": {
                    "type": "string",
                    "description": "The exact job title extracted from the job description."
                },
                "match_score": {
                    "type": "integer",
                    "description": "Score from 0 to 100 indicating how well the resume matches the job description."
                },
                "match_reason": {
                    "type": "string",
                    "description": "A brief explanation of why this score was given."
                },
                "required_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of key skills explicitly required in the job description."
                },
                "is_curve_ball": {
                    "type": "boolean",
                    "description": "True if the job description contains unusual or exclusionary requirements not typical for the role."
                },
                "curve_ball_reason": {
                    "type": "string",
                    "description": "Explanation of the curve ball requirement, if any."
                }
            },
            "required": ["job_title", "match_score", "match_reason", "required_skills", "is_curve_ball"]
        }

    async def evaluate_job(self, job_text: str, user_resume: str, company_name: str) -> Dict[str, Any]:
        """
        Accepts raw, cleaned job text and the user's resume.
        Calls llm_service to generate a semantic match score, extract skills, and determine alignment.
        """
        prompt = f"""
You are an expert technical recruiter analyzing a job description for {company_name}.
Evaluate the following Job Description against the Candidate's Resume.

Candidate Resume:
{user_resume}

Job Description:
{job_text}

Analyze the job description carefully and output a JSON response matching the required schema.
"""
        
        try:
            result = await self.llm_service.generate_structured_output(
                prompt=prompt,
                schema=self.evaluation_schema
            )
            return result
        except Exception as e:
            logger.error(f"Error during job evaluation: {e}")
            return {
                "job_title": "Discovered Job Role",
                "match_score": 0,
                "match_reason": f"Evaluation failed: {str(e)}",
                "required_skills": [],
                "is_curve_ball": False,
                "curve_ball_reason": None
            }
