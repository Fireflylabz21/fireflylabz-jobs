"""Sync Tally form https://tally.so/r/QKgdWX -> Supabase subscribers (free, no GCP).
Usage: set TALLY_API_KEY + TALLY_FORM_ID in .env, then: python sync_tally.py
"""
import os
import re
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
TALLY_API_KEY = os.getenv("TALLY_API_KEY", "")
TALLY_FORM_ID = os.getenv("TALLY_FORM_ID", "QKgdWX")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _answer_text(ans) -> str:
    if ans is None:
        return ""
    if isinstance(ans, str):
        return ans.strip()
    if isinstance(ans, (int, float)):
        return str(ans)
    if isinstance(ans, list):
        parts = []
        for a in ans:
            if isinstance(a, dict):
                parts.append(str(a.get("text") or a.get("name") or a.get("url") or ""))
            else:
                parts.append(str(a))
        return ", ".join(p for p in parts if p).strip()
    if isinstance(ans, dict):
        return str(ans.get("text") or ans.get("url") or ans.get("value") or "")
    return str(ans).strip()


def normalize_with_questions(submissions, questions) -> list:
    qtitle = {q.get("id"): str(q.get("title") or "").lower() for q in questions}
    rows = []
    for sub in submissions:
        m = {}
        for r in sub.get("responses", []):
            title = qtitle.get(r.get("questionId"), "")
            m[title] = _answer_text(r.get("answer"))

        def pick(*keys):
            for k in keys:
                for t, v in m.items():
                    if k in t and v:
                        return v
            return ""

        email = pick("email")
        name = pick("full name", "name")
        if not email or not EMAIL_RE.match(email):
            print(f"  [skip] {sub.get('id')} invalid email: {email!r}")
            continue
        exp_m = re.search(r"\d+", pick("years of experience") or "0")
        rows.append({
            "full_name": name or email.split("@")[0],
            "email": email.strip().lower(),
            "phone_number": pick("phone"),
            "primary_skillsets": pick("primary skillset", "primary skill"),
            "secondary_skillsets": pick("secondary skillset", "secondary skill"),
            "years_experience": int(exp_m.group()) if exp_m else 0,
            "current_company": pick("current company"),
            "current_ctc": pick("current ctc"),
            "notice_period": pick("notice period"),
            "current_location": pick("current location"),
            "expected_location": pick("expected location"),
            "resume_url": pick("upload resume", "resume"),
            "tally_response_id": sub.get("id"),
        })
    return rows


def upsert_rows(rows):
    if not SUPABASE_DB_URL:
        raise ValueError("SUPABASE_DB_URL missing.")
    conn = psycopg2.connect(SUPABASE_DB_URL, cursor_factory=RealDictCursor)
    n_new = n_upd = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute("SELECT id FROM subscribers WHERE email = %s;", (r["email"],))
            exists = cur.fetchone()
            if exists:
                cur.execute(
                    """UPDATE subscribers SET full_name=%s, phone_number=%s,
                       primary_skillsets=%s, secondary_skillsets=%s, years_experience=%s,
                       current_company=%s, current_ctc=%s, notice_period=%s,
                       current_location=%s, expected_location=%s, resume_url=%s,
                       tally_response_id=COALESCE(tally_response_id,%s) WHERE email=%s;""",
                    (r["full_name"], r["phone_number"], r["primary_skillsets"],
                     r["secondary_skillsets"], r["years_experience"], r["current_company"],
                     r["current_ctc"], r["notice_period"], r["current_location"],
                     r["expected_location"], r["resume_url"], r["tally_response_id"], r["email"]))
                n_upd += 1
            else:
                cur.execute(
                    """INSERT INTO subscribers (full_name, email, phone_number, primary_skillsets,
                       secondary_skillsets, years_experience, current_company, current_ctc,
                       notice_period, current_location, expected_location, resume_url,
                       tally_response_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);""",
                    (r["full_name"], r["email"], r["phone_number"], r["primary_skillsets"],
                     r["secondary_skillsets"], r["years_experience"], r["current_company"],
                     r["current_ctc"], r["notice_period"], r["current_location"],
                     r["expected_location"], r["resume_url"], r["tally_response_id"]))
                n_new += 1
    conn.commit()
    conn.close()
    print(f"  [db] upserted: new={n_new} updated={n_upd}")
    return n_new, n_upd


def main():
    print("Sync Tally -> Supabase subscribers...")
    if not TALLY_API_KEY:
        raise ValueError("Set TALLY_API_KEY in .env first (Tally -> Settings -> API).")
    url = f"https://api.tally.so/forms/{TALLY_FORM_ID}/submissions"
    headers = {"Authorization": f"Bearer {TALLY_API_KEY}"}
    out, questions, page = [], [], 1
    while True:
        r = requests.get(url, headers=headers, params={"page": page, "limit": 100}, timeout=30)
        r.raise_for_status()
        data = r.json()
        questions = data.get("questions", []) or questions
        out.extend(data.get("submissions", []))
        if not data.get("hasMore"):
            break
        page += 1
    print(f"  [tally] fetched {len(out)} submissions")
    rows = normalize_with_questions(out, questions)
    print(f"  [tally] valid rows: {len(rows)}")
    if not rows:
        print("  [tally] nothing to upsert (no completed submissions yet). Submit test at https://tally.so/r/QKgdWX")
        print("DONE.")
        return
    upsert_rows(rows)
    print("DONE.")


if __name__ == "__main__":
    main()
