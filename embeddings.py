"""Gemini embeddings (gemini-embedding-001, 3072-dim, free tier)."""
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_EMBED_MODEL

_configured = False


def _ensure_configured():
    global _configured
    if not _configured:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set.")
        genai.configure(api_key=GEMINI_API_KEY)
        _configured = True


def generate_embedding(text: str) -> list:
    """Return 768-dim vector (truncated Matryoshka) for retrieval_document task."""
    _ensure_configured()
    text = (text or "").strip()
    if not text:
        text = "general job seeker"
    resp = genai.embed_content(
        model=GEMINI_EMBED_MODEL,
        content=text,
        task_type="retrieval_document",
        output_dimensionality=768,  # keep pgvector HNSW <=2000 dims
    )
    emb = resp["embedding"] if isinstance(resp, dict) else resp.embedding
    return list(emb)


def profile_text_for(subscriber: dict) -> str:
    skills = ", ".join(subscriber.get("_skills_list") or [])
    return (
        f"Role: {subscriber.get('Primary Role', '')}. "
        f"Skills: {skills}. "
        f"Experience: {subscriber.get('_experience_years', 0)} years. "
        f"Location: {subscriber.get('_location', '')}. "
        f"Work preference: {subscriber.get('_work_pref', 'Flexible')}."
    )
