"""Supabase / PostgreSQL + pgvector helpers (768-dim for text-embedding-004)."""
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Any, Dict, List
from sheets_client import normalize_skills
from config import SUPABASE_DB_URL


def get_db_connection():
    if not SUPABASE_DB_URL:
        raise ValueError("SUPABASE_DB_URL is not set.")
    return psycopg2.connect(SUPABASE_DB_URL, cursor_factory=RealDictCursor)


def cleanup_old_jobs(conn, older_than_days: int = 14) -> int:
    """Delete jobs older than N days to stay under Supabase 500MB free tier. Returns row count."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM jobs WHERE posted_at < NOW() - (%s || ' days')::INTERVAL;", (str(older_than_days),))
        deleted = cur.rowcount
    conn.commit()
    return deleted


def db_row_to_subscriber(r: Dict[str, Any]) -> Dict[str, Any]:
    """Map subscribers table row -> canonical keys expected by matcher/agent/emailer/main."""
    skills_combined = ", ".join(
        s for s in [str(r.get("primary_skillsets") or "").strip(),
                    str(r.get("secondary_skillsets") or "").strip()] if s)
    try:
        exp = int(r.get("years_experience") or 0)
    except (TypeError, ValueError):
        exp = 0
    loc = str(r.get("expected_location") or r.get("current_location") or "").strip()
    email = str(r.get("email") or "").strip()
    name = str(r.get("full_name") or "").strip()
    sub: Dict[str, Any] = {
        "Full Name": name,
        "Email Address": email,
        "Primary Role": str(r.get("primary_skillsets") or "").strip(),
        "Key Skillsets": skills_combined,
        "Years of Experience": exp,
        "Work Preference": "Flexible",
        "Preferred Location": loc,
        "Status": str(r.get("status") or "Active"),
        "Last Newsletter Sent": str(r.get("last_sent") or ""),
        "Execution Notes": str(r.get("notes") or ""),
        "_row_number": None,
        "_db_id": str(r.get("id") or ""),
        "_skills_list": normalize_skills(skills_combined),
        "_experience_years": exp,
        "_work_pref": "Flexible",
        "_location": loc,
        "_status_norm": str(r.get("status") or "Active").strip().lower(),
        "_email_norm": email.lower(),
        "_role_norm": str(r.get("primary_skillsets") or "").strip(),
        "_current_company": str(r.get("current_company") or ""),
        "_current_ctc": str(r.get("current_ctc") or ""),
        "_notice_period": str(r.get("notice_period") or ""),
        "_phone": str(r.get("phone_number") or ""),
        "_resume_url": str(r.get("resume_url") or ""),
        "_valid": True,
        "_invalid_reason": "",
        "_db_row": dict(r),
    }
    return sub


def get_active_subscribers_db(conn) -> tuple:
    """DB-first read for Tally-sourced subscribers. Returns (active, skipped)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM subscribers
               WHERE COALESCE(status,'Active') = 'Active'
                 AND email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$'
                 AND (last_sent IS NULL OR last_sent < CURRENT_DATE)
               ORDER BY created_at ASC;""")
        rows = cur.fetchall()
    active = [db_row_to_subscriber(dict(r)) for r in rows]
    return active, []


def update_subscriber_writeback(conn, email: str, sent_date: str | None, notes: str) -> None:
    """DB writeback: UPDATE subscribers SET last_sent + notes WHERE email."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE subscribers SET last_sent = %s, notes = %s WHERE email = %s;",
            (sent_date, notes[:500], email))
        conn.commit()


def already_sent_today_db(last_sent) -> bool:
    import datetime as _dt
    if not last_sent:
        return False
    today = _dt.date.today().isoformat()
    return str(last_sent).strip()[:10] == today
