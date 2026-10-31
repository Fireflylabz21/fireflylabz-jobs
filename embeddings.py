"""Gemini embeddings (gemini-embedding-001, 3072-dim, free tier)."""
import google.generativeai as genai
from typing import Optional
from config import GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK, GEMINI_EMBED_MODEL
from telemetry import record_embed

_configured_key = None


def _ensure_configured():
    global _configured_key
    if _configured_key is not None:
        genai.configure(api_key=_configured_key)
        return
    for key in (GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK):
        if key:
            try:
                genai.configure(api_key=key)
                genai.embed_content(model=GEMINI_EMBED_MODEL, content="probe", output_dimensionality=768, task_type="retrieval_document")
                _configured_key = key
                return
            except Exception:
                continue
    raise ValueError("No valid GEMINI API key for embeddings.")


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
    record_embed(len(text) // 4)
    return list(emb)


class EmbeddingResult:
    """Wrapper so callers can use emb.embedding (like google.generativeai types)."""
    def __init__(self, embedding_list: list):
        self.embedding = embedding_list


def get_gemini_embedding(text: str) -> Optional[EmbeddingResult]:
    """Return an EmbeddingResult (with .embedding attr) or None on failure."""
    try:
        emb = generate_embedding(text)
        return EmbeddingResult(emb)
    except Exception:
        return None


def profile_text_for(subscriber: dict) -> str:
    skills = ", ".join(subscriber.get("_skills_list") or [])
    return (
        f"Role: {subscriber.get('Primary Role', '')}. "
        f"Skills: {skills}. "
        f"Experience: {subscriber.get('_experience_years', 0)} years. "
        f"Location: {subscriber.get('_location', '')}. "
        f"Work preference: {subscriber.get('_work_pref', 'Flexible')}."
    )
