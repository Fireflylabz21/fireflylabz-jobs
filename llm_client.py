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
    # 1. Gemini primary + fallback
    for key in (GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK):
        if not key:
            continue
        try:
            client = _gemini_client(key)
            cfg = None
            if json_mode:
                cfg = types.GenerateContentConfig(response_mime_type="application/json")
            resp = client.models.generate_content(model=GEMINI_LLM_MODEL, contents=prompt, config=cfg)
            text = getattr(resp, "text", None)
            if text:
                usage = getattr(resp, "usage_metadata", None)
                pt = getattr(usage, "prompt_token_count", 0) if usage else 0
                ct = getattr(usage, "candidates_token_count", 0) if usage else 0
                if not pt:
                    pt = len(prompt) // 4
                if not ct:
                    ct = len(text) // 4
                record_llm("gemini", GEMINI_LLM_MODEL, pt, ct)
                return text
        except Exception:
            continue

    # 2. OpenRouter
    if OPENROUTER_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=60)
            if r.ok:
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                if content:
                    usage = data.get("usage", {}) or {}
                    record_llm("openrouter", OPENROUTER_MODEL, usage.get("prompt_tokens", 0) or len(prompt)//4, usage.get("completion_tokens", 0) or len(content)//4)
                    return content
        except Exception:
            pass

    # 3. DeepSeek
    if DEEPSEEK_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            r = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=60)
            if r.ok:
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                if content:
                    usage = data.get("usage", {}) or {}
                    record_llm("deepseek", DEEPSEEK_MODEL, usage.get("prompt_tokens", 0) or len(prompt)//4, usage.get("completion_tokens", 0) or len(content)//4)
                    return content
        except Exception:
            pass

    return None
