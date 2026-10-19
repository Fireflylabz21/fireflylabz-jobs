"""Google Sheets subscriber ingestion, validation & writeback (FR-1.x).

Auth priority (keyless-friendly for orgs with iam.disableServiceAccountKeyCreation):
  1. Service-account JSON string (GCP_SERVICE_ACCOUNT_KEY) - CI legacy
  2. Service-account file (GCP_SERVICE_ACCOUNT_FILE) - local legacy
  3. OAuth user token (GCP_OAUTH_TOKEN_FILE / token.json) - RECOMMENDED for local dev
  4. Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS / WIF) - CI keyless
"""
import json
import os
import re
from typing import Any, Dict, List, Tuple

import gspread
from google.oauth2.service_account import Credentials as SACredentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import (
    GCP_OAUTH_CLIENT_FILE,
    GCP_OAUTH_TOKEN_FILE,
    GCP_SERVICE_ACCOUNT_FILE,
    GCP_SERVICE_ACCOUNT_KEY,
    GOOGLE_SHEET_ID,
    GOOGLE_SHEET_NAME,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Your LIVE sheet headers (row 1) — code maps these via aliases, do NOT rename manually.
# Timestamp | Name | Email ID | Phone number | Skillset or Domain | Experience (in years)
# | Current Location | Preferred location | Current CTC | Expected CTC
# | Are you a immediate joiners (within 15 days) | Notice period | Upload your resume
# | current company | Email Address | Score [+ auto-added: Last Newsletter Sent | Execution Notes]
EXPECTED_HEADERS = [
    "Subscriber ID",
    "Full Name",
    "Email Address",
    "Primary Role",
    "Years of Experience",
    "Key Skillsets",
    "Work Preference",
    "Preferred Location",
    "Status",
    "Last Newsletter Sent",
    "Execution Notes",
]

# Aliases for your existing Google Form sheet (case-insensitive match).
FIELD_ALIASES = {
    "full_name": ["Full Name", "Name"],
    "email": ["Email Address", "Email ID", "Email"],
    "role": ["Primary Role", "Skillset or Domain", "Skillset", "Domain", "Role"],
    "experience": ["Years of Experience", "Experience (in years)", "Experience"],
    "skills": ["Key Skillsets", "Skillset or Domain", "Skillset", "Domain", "Skills"],
    "work_pref": ["Work Preference"],
    "location": ["Preferred Location", "Preferred location", "Current Location"],
    "status": ["Status"],
    "subscription": ["Subscription"],
    "last_sent": ["Last Newsletter Sent"],
    "notes": ["Execution Notes"],
}


def _lookup(row: Dict[str, Any], *aliases: str) -> Any:
    """Case-insensitive, whitespace-tolerant lookup. Returns '' if not found."""
    norm = {str(k).strip().lower(): v for k, v in row.items()}
    for a in aliases:
        v = norm.get(a.strip().lower())
        if v is not None and str(v).strip() != "":
            return v
    # also try first alias exact (to preserve empty vs missing distinction)
    return norm.get(aliases[0].strip().lower(), "")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VALID_WORK_PREFS = {"remote", "hybrid", "onsite"}


def _oauth_user_creds() -> UserCredentials | None:
    """3-legged OAuth (desktop app). Creates/refreshes token.json. No SA key needed."""
    if os.path.exists(GCP_OAUTH_TOKEN_FILE):
        creds = UserCredentials.from_authorized_user_file(GCP_OAUTH_TOKEN_FILE, SCOPES)
        if creds.valid:
            return creds
        try:
            creds.refresh(Request())
            with open(GCP_OAUTH_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            return creds
        except Exception:
            pass  # fall through to fresh flow
    if not os.path.exists(GCP_OAUTH_CLIENT_FILE):
        return None
    flow = InstalledAppFlow.from_client_secrets_file(GCP_OAUTH_CLIENT_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(GCP_OAUTH_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    return creds


def build_gspread_client() -> gspread.Client:
    # 1. SA JSON string (GitHub Secret legacy)
    if GCP_SERVICE_ACCOUNT_KEY:
        info = json.loads(GCP_SERVICE_ACCOUNT_KEY)
        creds = SACredentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)
    # 2. SA file (local legacy)
    if os.path.exists(GCP_SERVICE_ACCOUNT_FILE):
        creds = SACredentials.from_service_account_file(GCP_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return gspread.authorize(creds)
    # 3. OAuth user token (recommended when SA key creation is disabled by org policy)
    oauth = _oauth_user_creds()
    if oauth is not None:
        return gspread.authorize(oauth)
    # 4. ADC / Workload Identity Federation (GOOGLE_APPLICATION_CREDENTIALS env or gcloud default)
    try:
        import google.auth
        adc_creds, _ = google.auth.default(scopes=SCOPES)
        return gspread.authorize(adc_creds)
    except Exception as e:
        raise ValueError(
            "No GCP credentials found. Options:\n"
            f"  a) OAuth local: create Desktop-app OAuth client, save as {GCP_OAUTH_CLIENT_FILE}, "
            f"rerun (browser consent creates {GCP_OAUTH_TOKEN_FILE})\n"
            "  b) Workload Identity Federation for GitHub Actions (no keys, see README)\n"
            f"  c) Service-account key (blocked by your org policy iam.disableServiceAccountKeyCreation)\n"
            f"ADC error: {e}") from e


def open_sheet(client: gspread.Client, name: str = GOOGLE_SHEET_NAME):
    if GOOGLE_SHEET_ID:
        return client.open_by_key(GOOGLE_SHEET_ID)
    return client.open(name).sheet1


def normalize_skills(raw: Any) -> List[str]:
    """'React, TypeScript, Node.js' -> ['React','TypeScript','Node.js'] (FR-1.3)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = raw
    else:
        parts = str(raw).split(",")
    out = []
    for p in parts:
        s = str(p).strip().strip('"').strip("'")
        if s:
            out.append(s)
    # de-dupe preserving order (case-insensitive)
    seen, deduped = set(), []
    for s in out:
        k = s.lower()
        if k not in seen:
            seen.add(k)
            deduped.append(s)
    return deduped


def parse_experience(raw: Any) -> int:
    """Parse '5', '5 years', 5 -> 5. Invalid -> 0."""
    if raw is None or str(raw).strip() == "":
        return 0
    m = re.search(r"\d+", str(raw))
    return int(m.group()) if m else 0


def normalize_work_pref(raw: Any) -> str:
    v = str(raw or "Remote").strip().capitalize()
    if v.lower() not in VALID_WORK_PREFS:
        return "Remote"
    return v


def is_valid_email(email: Any) -> bool:
    return bool(email and EMAIL_RE.match(str(email).strip()))


def sanitize_subscriber(row: Dict[str, Any], row_number: int) -> Dict[str, Any]:
    """Return sanitized copy with helper keys + validation flag.

    Works with YOUR live Form sheet via FIELD_ALIASES:
      Name -> Full Name | Email ID / Email Address -> Email Address
      Skillset or Domain -> Primary Role + Key Skillsets
      Experience (in years) -> Years of Experience
      Preferred location / Current Location -> Preferred Location
    Missing Status col => treated as Active. Missing Work Preference => Remote.
    Also backfills canonical keys so main.py / agent.py / emailer.py work unchanged.
    """
    A = FIELD_ALIASES
    full_name = str(_lookup(row, *A["full_name"]) or "").strip()
    email = str(_lookup(row, *A["email"]) or "").strip()
    role = str(_lookup(row, *A["role"]) or "").strip()
    skills_raw = _lookup(row, *A["skills"])
    exp_raw = _lookup(row, *A["experience"])
    work_raw = _lookup(row, *A["work_pref"])
    location = str(_lookup(row, *A["location"]) or "").strip()
    status = str(_lookup(row, *A["status"]) or "").strip()
    subscription = str(_lookup(row, *A["subscription"]) or "Weekly").strip()  # optional col
    last_sent = str(_lookup(row, *A["last_sent"]) or "").strip()
    notes = str(_lookup(row, *A["notes"]) or "").strip()
    # extra context from your sheet (passed to agent prompt via profile, not PII)
    current_ctc = str(row.get("Current CTC", "") or "").strip()
    expected_ctc = str(row.get("Expected CTC", "") or "").strip()
    immediate = str(row.get("Are you a immediate joiners (within 15 days)", "") or "").strip()
    notice = str(row.get("Notice period", "") or "").strip()
    current_company = str(row.get("current company", "") or row.get("Current company", "") or "").strip()

    sub = dict(row)
    # backfill canonical keys for downstream modules
    sub["Full Name"] = full_name or sub.get("Full Name", "")
    sub["Email Address"] = email or sub.get("Email Address", "")
    sub["Primary Role"] = role or sub.get("Primary Role", "")
    sub["Key Skillsets"] = skills_raw if skills_raw != "" else sub.get("Key Skillsets", "")
    sub["Years of Experience"] = exp_raw if exp_raw != "" else sub.get("Years of Experience", "")
    sub["Work Preference"] = work_raw if str(work_raw or "").strip() else "Remote"
    sub["Preferred Location"] = location
    sub["Last Newsletter Sent"] = last_sent or sub.get("Last Newsletter Sent", "")
    sub["Execution Notes"] = notes or sub.get("Execution Notes", "")
    if not str(sub.get("Status", "") or "").strip() and not status:
        sub["Status"] = "Active"  # default when sheet has no Status column
    elif status:
        sub["Status"] = status

    sub["_row_number"] = row_number
    sub["_skills_list"] = normalize_skills(skills_raw)
    sub["_experience_years"] = parse_experience(exp_raw)
    sub["_work_pref"] = normalize_work_pref(work_raw if str(work_raw or "").strip() else "Remote")
    sub["_location"] = location
    sub["_status_norm"] = str(sub.get("Status", "") or "").strip().lower()
    sub["_email_norm"] = email.lower()
    sub["_role_norm"] = role
    # extras for debugging / future agent use
    sub["_current_ctc"] = current_ctc
    sub["_expected_ctc"] = expected_ctc
    sub["_immediate_joiner"] = immediate
    sub["_notice_period"] = notice
    sub["_current_company"] = current_company
    ok, reason = True, ""
    # No Status column in your sheet -> every row with valid email is Active.
    has_status_col = any(str(k).strip().lower() == "status" for k in row.keys())
    if has_status_col and sub["_status_norm"] != "active":
        ok, reason = False, f"skipped-status={sub.get('Status','')}"
    elif not is_valid_email(email):
        ok, reason = False, "invalid-email"
    elif "subscription" in {str(k).strip().lower() for k in row.keys()} and subscription.lower() != "weekly":
        ok, reason = False, f"skipped-subscription={subscription}"
    sub["_valid"] = ok
    sub["_invalid_reason"] = reason
    return sub


def ensure_writeback_columns(sheet) -> None:
    """Add 'Last Newsletter Sent' + 'Execution Notes' headers if missing (your Form sheet lacks them)."""
    headers = [str(h).strip() for h in sheet.row_values(1)]
    need = [h for h in ("Last Newsletter Sent", "Execution Notes") if h not in headers]
    if need:
        # append at end in one call
        sheet.update(f"{chr(64 + len(headers) + 1)}1:{chr(64 + len(headers) + len(need))}1", [need])
        print(f"  [sheets] added columns: {need}")


def get_active_subscribers(sheet) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """FR-1.2: read all rows in one batch call, filter Active + valid email + Weekly.

    Returns (active, skipped).
    """
    records = sheet.get_all_records()
    active, skipped = [], []
    for idx, row in enumerate(records, start=2):  # row 1 = header
        sub = sanitize_subscriber(row, idx)
        (active if sub["_valid"] else skipped).append(sub)
    return active, skipped


def col_index_by_header(sheet, header_name: str) -> int:
    headers = sheet.row_values(1)
    try:
        return headers.index(header_name) + 1
    except ValueError:
        # fall back to canonical positions (10/11) for writeback cols
        fallback = {"Last Newsletter Sent": 10, "Execution Notes": 11}
        if header_name in fallback:
            return fallback[header_name]
        raise


def update_writeback(sheet, row_idx: int, sent_date: str, notes: str):
    """FR-1.4: update 'Last Newsletter Sent' + 'Execution Notes' by header lookup."""
    c_sent = col_index_by_header(sheet, "Last Newsletter Sent")
    c_notes = col_index_by_header(sheet, "Execution Notes")
    sheet.update_cell(row_idx, c_sent, sent_date)
    sheet.update_cell(row_idx, c_notes, notes)
