import json
import os
from typing import Optional

import requests
from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK, GEMINI_LLM_MODEL,
    OPENROUTER_API_KEY, OPENROUTER_MODEL,
    DEEPSEEK_API_KEY, DEEPSEEK_MODEL,
)
from telemetry import record_llm


def _gemini_client(key: str):
    return genai.Client(api_key=key)


def generate_text(prompt: str, json_mode: bool = False) -> Optional[str]:
    """LLM fallback chain: Gemini -> DeepSeek -> OpenRouter.

    Returns parsed text on success, or None if all providers failed.
    """
    for provider, model, api_key, base_url in (
        ("gemini", GEMINI_LLM_MODEL, GEMINI_API_KEY, None),
        ("deepseek", DEEPSEEK_MODEL, DEEPSEEK_API_KEY, None),
        ("openrouter", OPENROUTER_MODEL, OPENROUTER_API_KEY, "https://openrouter.ai/api/v1"),
    ):
        if not api_key:
            continue

        try:
            if provider == "gemini":
                client = _gemini_client(key)
                cfg = None
                if json_mode:
                    cfg = types.GenerateContentConfig(response_mime_type="application/json")
                resp = client.models.generate_content(
                    model=model, contents=prompt, config=cfg
                )
                text = getattr(resp, "text", None)
                if not text:
                    continue
                usage = getattr(resp, "usage_metadata", None)
                pt = getattr(usage, "prompt_token_count", 0) if usage else 0
                ct = getattr(usage, "candidates_token_count", 0) if usage else 0
                if not pt:
                    pt = len(prompt) // 4
                if not ct:
                    ct = len(text) // 4
                record_llm("gemini", model, pt, ct)
                return text

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            if base_url == "https://openrouter.ai/api/v1":
                r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                                 headers=headers, json=payload, timeout=60)
            else:
                r = requests.post("https://api.deepseek.com/chat/completions",
                                 headers=headers, json=payload, timeout=60)

            if r.ok:
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                if content:
                    usage = data.get("usage", {}) or {}
                    record_llm(provider, model,
                               usage.get("prompt_tokens", 0) or len(prompt) // 4,
                               usage.get("completion_tokens", 0) or len(content) // 4)
                    return content
        except Exception:
            continue

    return None
