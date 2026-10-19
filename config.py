"""Central configuration loader.
Loads .env locally, falls back to process env (GitHub Actions).
GCP auth priority: SA JSON string (CI) > SA file > OAuth user token > ADC/WIF.
"""
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_LLM_MODEL = os.getenv("GEMINI_LLM_MODEL", "models/gemini-flash-latest")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")
# Primary: full Postgres URI (psycopg2). Alternate: SUPABASE_URL + SUPABASE_KEY (supabase-py).
UNSUBSCRIBE_BASE_URL = os.getenv("UNSUBSCRIBE_BASE_URL", "")
UNSUBSCRIBE_SECRET = os.getenv("UNSUBSCRIBE_SECRET", "")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")  # anon key for reads, service_role for writes
# --- Email provider switch ($0): brevo (300/day free) primary, resend fallback ---
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "brevo").strip().lower()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "")
BREVO_SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "FireflyLabz Jobs")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Job Newsletter Subscribers")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")  # optional: open by ID (more reliable than name)
GCP_SERVICE_ACCOUNT_KEY = os.getenv("GCP_SERVICE_ACCOUNT_KEY", "")  # JSON string (CI)
GCP_SERVICE_ACCOUNT_FILE = os.getenv("GCP_SERVICE_ACCOUNT_FILE", "gcp_key.json")  # local SA file
# OAuth desktop-app fallback (use when iam.disableServiceAccountKeyCreation blocks SA keys)
GCP_OAUTH_CLIENT_FILE = os.getenv("GCP_OAUTH_CLIENT_FILE", "oauth_client.json")
GCP_OAUTH_TOKEN_FILE = os.getenv("GCP_OAUTH_TOKEN_FILE", "token.json")
FROM_EMAIL = os.getenv("FROM_EMAIL", "Job Newsletter <newsletter@yourdomain.com>")
LOGO_LIGHT_URL = os.getenv("LOGO_LIGHT_URL", "")
LOGO_DARK_URL = os.getenv("LOGO_DARK_URL", "")
BANNER_URL = os.getenv("BANNER_URL", "")
BRAND_WEBSITE = os.getenv("BRAND_WEBSITE", "https://fireflylabz.example.com")

MAX_SUBSCRIBERS_PER_RUN = int(os.getenv("MAX_SUBSCRIBERS_PER_RUN", "100"))
THROTTLE_SECONDS = float(os.getenv("THROTTLE_SECONDS", "4.5"))
JOB_LOOKBACK_DAYS = int(os.getenv("JOB_LOOKBACK_DAYS", "14"))
# Drip queue: Brevo 300/day free -> send 280/day buffer across Mon-Thu (~1120/week $0).
BATCH_LIMIT = int(os.getenv("BATCH_LIMIT", "280"))
DRY_RUN = os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes")

REQUIRED_ENV_LIVE = ["GEMINI_API_KEY", "SUPABASE_DB_URL"]


def email_configured() -> tuple:
    """Return (provider, ok, hint). At least one of Brevo/Resend must be set."""
    from os import getenv as _g
    prov = (_g("EMAIL_PROVIDER", "brevo") or "brevo").strip().lower()
    has_brevo = bool(_g("BREVO_API_KEY") and (_g("BREVO_SENDER_EMAIL") or _g("FROM_EMAIL")))
    has_resend = bool(_g("RESEND_API_KEY"))
    if prov == "brevo" and has_brevo:
        return prov, True, ""
    if prov == "resend" and has_resend:
        return prov, True, ""
    if has_brevo:
        return "brevo", True, "fallback"
    if has_resend:
        return "resend", True, "fallback"
    return prov, False, "Set BREVO_API_KEY+BREVO_SENDER_EMAIL or RESEND_API_KEY."


def gcp_auth_available() -> bool:
    """Legacy Sheets path — kept for backwards compat, no longer required (Tally+DB)."""
    return True


def validate_env(strict: bool = True) -> list:
    """Return list of missing var names. Raise if strict and DRY_RUN is False."""
    missing = [k for k in REQUIRED_ENV_LIVE if not os.getenv(k)]
    if not gcp_auth_available():
        missing.append("GCP auth (SA key/file, OAuth token.json, or ADC/WIF)")
    if missing and strict and not DRY_RUN:
        raise ValueError(f"Missing required env vars: {', '.join(missing)}. "
                         "Copy .env.example to .env and fill values, or set GitHub Secrets.")
    return missing
