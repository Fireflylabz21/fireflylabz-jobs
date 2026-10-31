"""Lightweight telemetry collector + daily email report."""
import os
import time
import requests
from config import (
    EMAIL_PROVIDER, BREVO_API_KEY, BREVO_SENDER_EMAIL, BREVO_SENDER_NAME,
    FROM_EMAIL, RESEND_API_KEY,
)

TELEMETRY_EMAIL = os.getenv("TELEMETRY_EMAIL", os.getenv("FROM_EMAIL", ""))

_state = {
    "llm_calls": [],
    "embed_calls": 0,
    "embed_tokens": 0,
    "scrape": {},
    "ingest": {},
    "start_time": time.time(),
}


def record_llm(provider: str, model: str, prompt_tokens: int = 0, completion_tokens: int = 0):
    _state["llm_calls"].append({
        "provider": provider,
        "model": model,
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
    })


def record_embed(tokens: int = 0):
    _state["embed_calls"] += 1
    _state["embed_tokens"] += int(tokens or 0)


def record_scrape(stats: dict):
    _state["scrape"] = stats or {}


def record_ingest(stats: dict):
    _state["ingest"] = stats or {}


def _llm_summary():
    by_provider = {}
    total_prompt = total_completion = 0
    for c in _state["llm_calls"]:
        key = f"{c['provider']} / {c['model']}"
        by_provider.setdefault(key, {"calls": 0, "prompt": 0, "completion": 0})
        by_provider[key]["calls"] += 1
        by_provider[key]["prompt"] += c["prompt_tokens"]
        by_provider[key]["completion"] += c["completion_tokens"]
        total_prompt += c["prompt_tokens"]
        total_completion += c["completion_tokens"]
    return by_provider, total_prompt, total_completion


def build_report(title: str = "Daily Telemetry Report") -> str:
    elapsed = time.time() - _state["start_time"]
    by_provider, tp, tc = _llm_summary()
    lines = []
    lines.append(f"=== {title} ===")
    lines.append(f"Elapsed: {elapsed:.1f}s")
    lines.append("")
    lines.append("--- Scraper ---")
    for k, v in (_state["scrape"] or {}).items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("--- Ingest ---")
    for k, v in (_state["ingest"] or {}).items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("--- LLM Usage ---")
    lines.append(f"  LLM calls: {len(_state['llm_calls'])}")
    for key, v in by_provider.items():
        lines.append(f"    {key}: calls={v['calls']} prompt_tokens~={v['prompt']} completion_tokens~={v['completion']}")
    lines.append(f"  Total prompt tokens~={tp}")
    lines.append(f"  Total completion tokens~={tc}")
    lines.append(f"  Total LLM tokens~={tp + tc}")
    lines.append("")
    lines.append("--- Embeddings ---")
    lines.append(f"  Embed calls: {_state['embed_calls']}")
    lines.append(f"  Embed tokens~={_state['embed_tokens']}")
    lines.append("")
    lines.append(f"Report generated at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    return "\n".join(lines)


def send_report(subject: str = "Daily Telemetry Report"):
    body = build_report(subject)
    print(body)
    if not TELEMETRY_EMAIL:
        print("[telemetry] No TELEMETRY_EMAIL set; report printed only.")
        return False
    if EMAIL_PROVIDER.lower() == "brevo" and BREVO_API_KEY and BREVO_SENDER_EMAIL:
        try:
            payload = {
                "sender": {"name": BREVO_SENDER_NAME or "Telemetry", "email": BREVO_SENDER_EMAIL},
                "to": [{"email": TELEMETRY_EMAIL}],
                "subject": subject,
                "textContent": body,
            }
            headers = {"api-key": BREVO_API_KEY, "content-type": "application/json", "accept": "application/json"}
            r = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers, timeout=30)
            if r.status_code < 400:
                print(f"[telemetry] Report emailed via Brevo to {TELEMETRY_EMAIL}")
                return True
            print(f"[telemetry] Brevo error {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[telemetry] Brevo send failed: {e}")
    if RESEND_API_KEY:
        try:
            payload = {
                "from": FROM_EMAIL or BREVO_SENDER_EMAIL,
                "to": [TELEMETRY_EMAIL],
                "subject": subject,
                "text": body,
            }
            headers = {"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"}
            r = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=30)
            if r.status_code < 400:
                print(f"[telemetry] Report emailed via Resend to {TELEMETRY_EMAIL}")
                return True
            print(f"[telemetry] Resend error {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[telemetry] Resend send failed: {e}")
    return False
