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


def week_monday() -> str:
    """Current week key (Monday date) for email_queue sharding."""
    import datetime as _dt
    today = _dt.date.today()
    monday = today - _dt.timedelta(days=today.weekday())
    return monday.isoformat()


def score_priority(r: Dict[str, Any]) -> int:
    """Higher = send first. Fresh + niche + exact-city wins, no starvation.
    new (never sent) +100 | not sent in 14d +30 | 10y+ exp niche +20 |
    exact-city in skills-area +10 | long name (proxy engaged) +5.
    """
    score = 0
    if not r.get("last_sent"):
        score += 100
    try:
        exp = int(r.get("years_experience") or 0)
        if exp >= 10:
            score += 20
        elif exp >= 5:
            score += 10
    except (TypeError, ValueError):
        pass
    loc = str(r.get("expected_location") or r.get("current_location") or "").strip().lower()
    if loc in ("bangalore", "bengaluru", "hyderabad", "chennai"):
        score += 10
    if len(str(r.get("full_name") or "")) > 8:
        score += 5
    return score


def enqueue_week(conn, week: str | None = None) -> tuple:
    """Sunday step: enqueue all Active subs for this week with priority. Returns (queued, total)."""
    import datetime as _dt
    week = week or week_monday()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT email, full_name, years_experience, last_sent,
                      expected_location, current_location
               FROM subscribers WHERE COALESCE(status,'Active')='Active';""")
        rows = [dict(r) for r in cur.fetchall()]
        queued = 0
        for r in rows:
            email = str(r.get("email") or "").strip()
            if not email or "@" not in email:
                continue
            pri = score_priority(r)
            cur.execute(
                """INSERT INTO email_queue (email, week, priority, status)
                   VALUES (%s,%s,%s,'pending')
                   ON CONFLICT (email, week) DO UPDATE SET priority=EXCLUDED.priority
                   WHERE email_queue.status='pending';""",
                (email, week, pri))
            if cur.rowcount:
                queued += 1
        # mark unsubscribed/invalid as skipped so batch never picks them
        cur.execute(
            """UPDATE email_queue q SET status='skipped'
               WHERE q.week=%s AND q.status='pending'
                 AND NOT EXISTS (SELECT 1 FROM subscribers s
                   WHERE lower(s.email)=lower(q.email)
                     AND COALESCE(s.status,'Active')='Active');""",
            (week,))
    conn.commit()
    return queued, len(rows)


def fetch_batch(conn, week: str | None = None, limit: int = 280) -> list:
    """Mon-Thu step: next pending batch ordered by priority. Returns subscriber dicts."""
    week = week or week_monday()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT s.* FROM email_queue q JOIN subscribers s ON lower(s.email)=lower(q.email)
               WHERE q.week=%s AND q.status='pending'
                 AND COALESCE(s.status,'Active')='Active'
               ORDER BY q.priority DESC, s.created_at ASC LIMIT %s;""",
            (week, limit))
        rows = [dict(r) for r in cur.fetchall()]
    return [db_row_to_subscriber(r) for r in rows]


def mark_queued(conn, email: str, week: str, status: str, error: str = "") -> None:
    with conn.cursor() as cur:
        if status == "sent":
            cur.execute(
                """UPDATE email_queue SET status='sent', sent_at=NOW(), attempts=attempts+1
                   WHERE email=%s AND week=%s;""",
                (email, week))
        else:
            cur.execute(
                """UPDATE email_queue SET status=%s, attempts=attempts+1, last_error=%s
                   WHERE email=%s AND week=%s;""",
                (status, error[:300], email, week))
    conn.commit()


def queue_stats(conn, week: str | None = None) -> dict:
    week = week or week_monday()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT status, COUNT(*) c FROM email_queue WHERE week=%s GROUP BY status;""",
            (week,))
        out = {}
        for r in cur.fetchall():
            d = dict(r)
            out[str(d.get("status"))] = int(d.get("c", 0))
        return out
