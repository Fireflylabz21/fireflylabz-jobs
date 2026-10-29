"""Check DB constraints."""
"""Temporary DB check script."""
from db import get_db_connection

conn = get_db_connection()
with conn.cursor() as cur:
    cur.execute("SELECT id, title, company, apply_url, posted_at FROM jobs ORDER BY posted_at DESC LIMIT 15;")
    rows = cur.fetchall()
    print(f"Total jobs in DB: {len(rows)}")
    for r in rows:
        print(f"  - {r['title']} @ {r['company']} ({r['apply_url'][:80]})")
conn.close()