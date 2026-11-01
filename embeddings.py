"""Gemini embeddings (gemini-embedding-001, 768-dim via Matryoshka, free tier)."""
from typing import Optional
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK, GEMINI_EMBED_MODEL
from telemetry import record_embed

_configured_key = None


def _client_for(key: str):
    return genai.Client(api_key=key)


def _ensure_configured():
    global _configured_key
    if _configured_key is not None:
        return _configured_key
    for key in (GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK):
        if not key:
            continue
        try:
            c = _client_for(key)
            c.models.embed_content(
                model=GEMINI_EMBED_MODEL,
                contents="probe",
                config=types.EmbedContentConfig(output_dimensionality=768, task_type="RETRIEVAL_DOCUMENT"),
            )
            _configured_key = key
            return key
        except Exception:
            continue
    raise ValueError("No valid GEMINI API key for embeddings.")


def generate_embedding(text: str) -> list:
    key = _ensure_configured()
    client = _client_for(key)
    text = (text or "").strip()
    if not text:
        text = "general job seeker"
    resp = client.models.embed_content(
        model=GEMINI_EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=768, task_type="RETRIEVAL_DOCUMENT"),
    )
    emb = resp.embeddings[0].values if getattr(resp, "embeddings", None) else resp.embedding.values
    record_embed(len(text) // 4)
    return list(emb)


class EmbeddingResult:
    def __init__(self, embedding_list: list):
        self.embedding = embedding_list


def get_gemini_embedding(text: str) -> Optional[EmbeddingResult]:
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
