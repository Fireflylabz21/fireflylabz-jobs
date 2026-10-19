"""Auto-ingest REAL jobs weekly ($0, no API keys).
Sources (free, no auth):
  1. Remotive (remote OK): https://remoteok.com/api (no key, be nice: 1 req/min)
  2. Arbeitnow (remote EU/US): https://www.arbeitnow.com/api/job-board-api
Falls back gracefully; dedupes by apply_url; embeds via Gemini; marks posted_at=NOW.
Run: python ingest_jobs.py [--limit 30]
Cron order: ingest_jobs.py -> sync_tally.py -> main.py
"""
import argparse
import sys
import time
import requests
from db import get_db_connection
from embeddings import generate_embedding

HEADERS = {"User-Agent": "FireflyLabz-JobBot/1.0 (+weekly digest, contact: jobs@fireflylabz.example.com)"}

SKILL_HINTS = ["python", "java", "selenium", "react", "sql", "aws", "presales", "saas",
               "data science", "machine learning", "consulting", "api"]


def _norm_remoteok(items, limit: int):
    out = []
    for j in items:
        if not isinstance(j, dict) or not j.get("url"):
            continue
        tags = [str(t) for t in (j.get("tags") or [])]
        out.append({
            "title": str(j.get("position", "") or "")[:200],
            "company": str(j.get("company", "") or "")[:200],
            "location": "Remote",
            "work_style": "Remote",
            "min_experience": 1, "max_experience": 10,
            "required_skills": (tags[:6] or ["Generalist"]),
            "description_text": (str(j.get("description", "") or "")[:800] or
                                 f"{j.get('position','')} at {j.get('company','')}. " + ", ".join(tags[:6])),
            "apply_url": str(j.get("url", ""))[:500],
        })
        if len(out) >= limit:
            break
    return out


def _norm_arbeitnow(items, limit: int):
    out = []
    for j in (items or []):
        if not isinstance(j, dict) or not j.get("url"):
            continue
        tags = [str(t) for t in (j.get("tags") or [])]
        loc = str(j.get("location", "") or "Remote")
        ws = "Remote" if "remote" in loc.lower() else "Hybrid"
        out.append({
            "title": str(j.get("title", "") or "")[:200],
            "company": str(j.get("company_name", "") or "")[:200],
            "location": loc[:200],
            "work_style": ws,
            "min_experience": 1, "max_experience": 10,
            "required_skills": (tags[:6] or ["Generalist"]),
            "description_text": (str(j.get("description", "") or "")[:800] or
                                 f"{j.get('title','')} at {j.get('company_name','')}."),
            "apply_url": str(j.get("url", ""))[:500],
        })
        if len(out) >= limit:
            break
    return out


def fetch_all(limit: int = 30):
    jobs = []
    # 1. RemoteOK
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) > 1:
            jobs += _norm_remoteok(data[1:], limit - len(jobs))
        print(f"  [ingest] remoteok: {len(jobs)} so far")
    except Exception as e:
        print(f"  [ingest] remoteok failed (non-fatal): {e}")
    time.sleep(2)
    # 2. Arbeitnow
    try:
        r = requests.get("https://www.arbeitnow.com/api/job-board-api", headers=HEADERS, timeout=30)
        r.raise_for_status()
        items = r.json().get("data", [])
        before = len(jobs)
        jobs += _norm_arbeitnow(items, limit - len(jobs))
        print(f"  [ingest] arbeitnow: +{len(jobs)-before}")
    except Exception as e:
        print(f"  [ingest] arbeitnow failed (non-fatal): {e}")
    return jobs[:limit]


def upsert_jobs(jobs) -> tuple:
    """Insert new by apply_url; returns (inserted, skipped)."""
    if not jobs:
        return 0, 0
    conn = get_db_connection()
    ins = skip = 0
    with conn.cursor() as cur:
        for j in jobs:
            if not j.get("apply_url") or not j.get("title"):
                skip += 1
                continue
            cur.execute("SELECT 1 FROM jobs WHERE apply_url=%s;", (j["apply_url"],))
            if cur.fetchone():
                skip += 1
                continue
            text = (f"{j['title']} at {j['company']}. {j['description_text']} "
                    f"Skills: {', '.join(j['required_skills'])} Location: {j['location']}")
            try:
                emb = generate_embedding(text)
            except Exception as e:
                print(f"  [ingest] embedding failed for {j['title'][:40]}: {e}")
                skip += 1
                continue
            cur.execute(
                """INSERT INTO jobs (title, company, location, work_style, min_experience,
                   max_experience, required_skills, description_text, apply_url, embedding)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)""",
                (j["title"], j["company"], j["location"], j["work_style"], j["min_experience"],
                 j["max_experience"], j["required_skills"], j["description_text"], j["apply_url"], emb))
            ins += 1
            time.sleep(1.5)  # Gemini embedding quota guard
    conn.commit()
    conn.close()
    return ins, skip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()
    print(f"Ingesting fresh jobs (limit={args.limit})...")
    jobs = fetch_all(args.limit)
    print(f"  [ingest] fetched {len(jobs)} candidates")
    ins, skip = upsert_jobs(jobs)
    print(f"DONE. inserted={ins} skipped(dupes)={skip}")


if __name__ == "__main__":
    main()
