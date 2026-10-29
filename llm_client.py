"""Unified LLM text generation with fallbacks: Gemini (primary/fallback) -> OpenRouter -> DeepSeek."""
import json
import os
from typing import Optional

import requests
import google.generativeai as genai

from config import (
    GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK, GEMINI_LLM_MODEL,
    OPENROUTER_API_KEY, OPENROUTER_MODEL,
    DEEPSEEK_API_KEY, DEEPSEEK_MODEL,
)


def generate_text(prompt: str, json_mode: bool = False) -> Optional[str]:
    # 1. Gemini primary + fallback
    for key in (GEMINI_API_KEY, GEMINI_API_KEY_FALLBACK):
        if not key:
            continue
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(GEMINI_LLM_MODEL)
            cfg = {"response_mime_type": "application/json"} if json_mode else {}
            resp = model.generate_content(prompt, generation_config=cfg)
            text = getattr(resp, "text", None)
            if text:
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
                    return content
        except Exception:
            pass

    return None