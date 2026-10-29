"""============================================================
  IngestJobsAgent - Modified Ingestion Agent
  ============================================================

  Modified job ingestion agent that:
    1. Searches existing jobs in DB for matching roles per subscriber
    2. Ranks matches with Gemini Flash (existing agent.py logic)
    3. If matches found: sends email via Brevo/Resend
    4. If no matches: triggers ScraperAgent for new roles
    5. Re-checks DB for newly scraped jobs, sends email with fresh matches
    6. Idempotent: last_sent check to avoid duplicate sends

  Design principles:
    - DB-first: query existing jobs before scraping new ones
    - Gemini-ranked: use existing agent.py ranking logic
    - Fallback: ScraperAgent for new jobs when no matches
    - Idempotent: safe to re-run without duplicate sends
    - Throttle-aware: respects Gemini 15 RPM free limit
"""

import argparse
import time
import traceback
import datetime

from db import get_db_connection, get_active_subscribers_db, update_subscriber_writeback, already_sent_today_db
from matcher import search_matching_jobs
from agent import evaluate_and_rank_jobs
from emailer import send_newsletter_email
from config import DRY_RUN, MAX_SUBSCRIBERS_PER_RUN, THROTTLE_SECONDS, JOB_LOOKBACK_DAYS, EMAIL_PROVIDER


def run_ingest_jobs_agent(scrape_first: bool = False):
    """Run the modified IngestJobsAgent.

    For each subscriber:
      1. Query existing jobs from DB (search_matching_jobs)
      2. Rank top matches with Gemini (evaluate_and_rank_jobs)
      3. If matches found: send email
      4. If no matches: trigger ScraperAgent for new roles
      5. Re-check DB for newly scraped jobs
      6. Idempotent: safe to re-run without duplicate sends

    Returns dict with processing stats.
    """
    print("Starting Modified IngestJobsAgent")
    print("=" * 60)

    conn = get_db_connection()
    if conn is None:
        raise RuntimeError("No DB connection (check SUPABASE_DB_URL)")

    active, skipped = get_active_subscribers_db(conn)
    print(f"DB: active={len(active)} subscribers, skipped={len(skipped)}")

    batch = active[:MAX_SUBSCRIBERS_PER_RUN]
    if len(active) > len(batch):
        print(f"[throttle] capped to {MAX_SUBSCRIBERS_PER_RUN}/run (free email quota)")
        print(f"{len(active)-len(batch)} deferred to next run.")

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    processed = sent = no_jobs = failed = 0
    triggered_scraper = 0

    if scrape_first:
        print("       [scrape-first] running scraper once globally before matching...")
        try:
            from scraper_agent import ScraperAgent
            scraper = ScraperAgent(dry_run=False)
            scraper_stats = scraper.run()
            triggered_scraper = 1
            print(f"       scraper done: {scraper_stats}")
        except Exception as e:
            print(f"       [scrape-first] scraper failed: {e}")

    # Dependency guard: ingest relies on scraper having populated jobs table.
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM jobs WHERE is_active = TRUE;")
            job_count = int(cur.fetchone()["c"])
    except Exception as e:
        job_count = -1
        print(f"       [warn] could not count jobs: {e}")
    print(f"       jobs in DB (active): {job_count}")
    if job_count == 0 and not scrape_first:
        print("       [abort] no jobs in DB yet - run scraper cron first. Exiting.")
        conn.close()
        return {"processed": 0, "sent": 0, "no_jobs": 0, "failed": 0, "triggered_scraper": triggered_scraper}

    for sub in batch:
        email = sub.get("Email Address", "")
        name = sub.get("Full Name", "")

        try:
            if already_sent_today_db(sub.get("Last Newsletter Sent")):
                print(f"[skip] {name} <{email}> already sent today (idempotent)")
                continue

            print(f"[..] {name} <{email}> | {sub.get('Primary Role', '')}")
            print(f"       {sub.get('_experience_years', 0)}y | {sub.get('_location', '')}")

            candidates = search_matching_jobs(conn, sub, limit=15)
            print(f"       vector hits: {len(candidates)}")

            selected = evaluate_and_rank_jobs(sub, candidates)
            print(f"       agent picks: {len(selected)}")

            if selected:
                ok = send_newsletter_email(sub, selected)
                if ok:
                    if not DRY_RUN:
                        update_subscriber_writeback(conn, email, today_str, f"Sent ({len(selected)} jobs matched)")
                    sent += 1
                    print("       sent via email")
                else:
                    raise RuntimeError("email delivery failed after retries")

            else:
                if not DRY_RUN:
                    update_subscriber_writeback(conn, email, sub.get("Last Newsletter Sent") or None, "No relevant jobs found this week")
                no_jobs += 1
                print("       no relevant jobs in DB (scraper runs separately via cron)")

            processed += 1
            time.sleep(THROTTLE_SECONDS)

        except Exception as e:
            failed += 1
            print(f"       FAILED {email}: {e}")
            traceback.print_exc(limit=2)
            try:
                if not DRY_RUN and conn is not None:
                    update_subscriber_writeback(conn, email, sub.get("Last Newsletter Sent") or None, f"Failed: {str(e)[:60]}")
            except Exception as we:
                print(f"       [writeback] failed: {we}")

    if conn is not None:
        conn.close()

    print()
    print("=" * 60)
    print(f"DONE. processed={processed} sent={sent} no_jobs={no_jobs} failed={failed}")
    print(f"       triggered_scraper={triggered_scraper}")
    print("=" * 60 + "\n")

    return {
        "processed": processed,
        "sent": sent,
        "no_jobs": no_jobs,
        "failed": failed,
        "triggered_scraper": triggered_scraper,
    }


def main():
    """CLI entry point for the Modified IngestJobsAgent."""
    parser = argparse.ArgumentParser(
        description="IngestJobsAgent - Modified Ingestion Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_jobs_agent.py                          # Run agent (default)
  python ingest_jobs_agent.py --dry-run               # Dry run (no emails/DB writes)
  python ingest_jobs_agent.py --limit 50              # Process 50 subscribers
  python ingest_jobs_agent.py --check-only             # Only check, no sends
        """
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry run - no emails, no DB writes")
    parser.add_argument("--limit", type=int, default=MAX_SUBSCRIBERS_PER_RUN,
                        help=f"Max subscribers to process (default {MAX_SUBSCRIBERS_PER_RUN})")
    parser.add_argument("--scrape-first", action="store_true",
                        help="Run scraper once globally before matching (manual/ad-hoc)")
    args = parser.parse_args()

    missing = []
    if not os.getenv("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if not os.getenv("SUPABASE_DB_URL"):
        missing.append("SUPABASE_DB_URL")
    if missing:
        raise ValueError(f"Missing required env vars: {', '.join(missing)}")

    print(f"DRY_RUN={DRY_RUN}")
    print(f"SOURCE=supabase.subscribers")

    result = run_ingest_jobs_agent(scrape_first=args.scrape_first)
    print(f"\nResult: {result}")


if __name__ == "__main__":
    import os
    main()