"""Tier 3 AI reasoning agent (FR-3.3) on Gemini 1.5 Flash.
- Strips PII (name/email) before LLM call (NFR privacy).
- Skill-gap analysis, selects top 3-5, writes 1-2 sentence rationale each.
- Forces JSON output, with safe fallback to top-3 vector hits.
"""
import json
from typing import Any, Dict, List
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_LLM_MODEL

_configured = False


def _ensure():
    global _configured
    if not _configured:
        genai.configure(api_key=GEMINI_API_KEY)
        _configured = True


def _anonymized_profile(subscriber: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "role": subscriber.get("Primary Role", ""),
        "years_experience": subscriber.get("_experience_years", 0),
        "skills": subscriber.get("_skills_list", []),
        "work_preference": subscriber.get("_work_pref", "Remote"),
        "preferred_location": subscriber.get("_location", ""),
    }


def _slim_jobs(candidate_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    slim = []
    for j in candidate_jobs:
        slim.append({
            "job_id": str(j.get("id")),
            "title": j.get("title"),
            "company": j.get("company"),
            "location": j.get("location"),
            "work_style": j.get("work_style"),
            "min_experience": j.get("min_experience"),
            "max_experience": j.get("max_experience"),
            "required_skills": j.get("required_skills"),
            "description": (j.get("description_text", "") or "")[:1200],
            "apply_url": j.get("apply_url"),
            "similarity": round(float(j.get("similarity", 0) or 0), 4),
        })
    return slim


def evaluate_and_rank_jobs(subscriber: Dict[str, Any],
                           candidate_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not candidate_jobs:
        return []
    _ensure()
    model = genai.GenerativeModel(GEMINI_LLM_MODEL)

    prompt = f"""
You are an expert career counselor. Match the anonymized candidate to jobs.

Candidate (PII removed):
{json.dumps(_anonymized_profile(subscriber))}

Candidate jobs (top 15 by vector similarity):
{json.dumps(_slim_jobs(candidate_jobs), default=str)}

Task:
1. Do a skill-gap check: separate core requirements vs nice-to-haves.
2. Pick the top 3 to 5 BEST matches (quality over quantity).
3. For each, write a 1-2 sentence personalized rationale referencing their role/skills.

Return ONLY a JSON array:
[{{"job_id": "<UUID>", "title": "<title>", "company": "<company>",
   "apply_url": "<url>", "match_rationale": "<1-2 sentences>"}}]
"""
    try:
        resp = model.generate_content(
            prompt, generation_config={"response_mime_type": "application/json"})
        data = json.loads(resp.text)
        # validate shape + enrich with candidate metadata for template (location/skills/exp)
        by_id = {str(j.get("id")): j for j in candidate_jobs}
        clean = []
        for d in data[:5]:
            if isinstance(d, dict) and d.get("job_id") and d.get("title"):
                src = by_id.get(str(d.get("job_id")), {})
                clean.append({
                    "job_id": str(d.get("job_id")),
                    "title": d.get("title"),
                    "company": d.get("company", src.get("company", "")),
                    "location": src.get("location", ""),
                    "work_style": src.get("work_style", ""),
                    "min_experience": src.get("min_experience"),
                    "max_experience": src.get("max_experience"),
                    "required_skills": src.get("required_skills", []),
                    "apply_url": d.get("apply_url", src.get("apply_url", "")),
                    "match_rationale": d.get("match_rationale", "Great match for your skillset."),
                })
        if clean:
            return clean
    except Exception as e:
        print(f"  [agent] Gemini parse error, falling back: {e}")

    # Fallback: top-3 vector hits with generic rationale (keep metadata for template)
    fb = []
    for j in candidate_jobs[:3]:
        fb.append({"job_id": str(j.get("id")), "title": j.get("title"),
                   "company": j.get("company"), "location": j.get("location"),
                   "work_style": j.get("work_style"),
                   "min_experience": j.get("min_experience"),
                   "max_experience": j.get("max_experience"),
                   "required_skills": j.get("required_skills", []),
                   "apply_url": j.get("apply_url"),
                   "match_rationale": "Strong skill overlap with your profile."})
    return fb
