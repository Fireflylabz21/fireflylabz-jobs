"""Alternate Supabase REST client (Format B: SUPABASE_URL + SUPABASE_KEY, no DB password).
Install: pip install supabase
Use when you cannot find/reset DB password. Requires RLS policies on subscribers/jobs
(see schema.sql RLS section) OR use service_role key for writes.

Your values (Project Settings -> API):
  SUPABASE_URL=https://kgdiydsokitpmpzwzwje.supabase.co
  SUPABASE_KEY=<anon public key, the eyJ... starting with your project ref>
"""
import os
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


def get_client():
    from supabase import create_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Set SUPABASE_URL + SUPABASE_KEY in .env (Project Settings -> API).")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def test_connection():
    sb = get_client()
    # subscribers table must exist (run schema.sql first)
    res = sb.table("subscribers").select("id", count="exact").limit(1).execute()
    jobs = sb.table("jobs").select("id", count="exact").limit(1).execute()
    print(f"  [supabase-rest] OK: subscribers={res.count} jobs={jobs.count}")
    return True


def fetch_active_subscribers(limit=100):
    sb = get_client()
    res = (sb.table("subscribers").select("*").eq("status", "Active")
           .is_("last_sent", "null").order("created_at").limit(limit).execute())
    return res.data or []


if __name__ == "__main__":
    test_connection()
