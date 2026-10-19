"""Weekly AI Job Newsletter pipeline ($0/month).
Flow: Tally->Supabase subscribers -> SQL prefilter + pgvector top15
      -> Gemini Flash top3-5 -> Resend -> Supabase writeback.
Idempotent: skips rows already stamped with today's date.
No Google Sheets / GCP auth needed.
"""
import datetime
import time
import traceback

from config import (
    DRY_RUN,
    JOB_LOOKBACK_DAYS,
    MAX_SUBSCRIBERS_PER_RUN,
    THROTTLE_SECONDS,
    validate_env,
)
from db import (
    already_sent_today_db,
    cleanup_old_jobs,
    get_active_subscribers_db,
    get_db_connection,
    update_subscriber_writeback,
)
from matcher import search_matching_jobs
from agent import evaluate_and_rank_jobs
from emailer import send_newsletter_email


def main():
    print("Starting $0 Weekly AI Job Newsletter Pipeline (Tally + Supabase)...")
    print(f"  DRY_RUN={DRY_RUN} SOURCE=supabase.subscribers LOOKBACK={JOB_LOOKBACK_DAYS}d")

    missing = validate_env(strict=False)
    if missing:
        print(f"  [warn] missing env: {missing} (continuing; failures will be logged per-row)")

    # --- Connect DB ---
    conn = None
    try:
        conn = get_db_connection()
        deleted = cleanup_old_jobs(conn, JOB_LOOKBACK_DAYS)
        print(f"  [db] cleanup removed {deleted} stale jobs.")
    except Exception as e:
        print(f"  [db] connection/cleanup failed: {e}")
        if not DRY_RUN:
            raise

    # --- Load subscribers from Supabase (synced from Tally via sync_tally.py) ---
    if conn is None:
        raise RuntimeError("No DB connection (check SUPABASE_DB_URL).")
    active, skipped = get_active_subscribers_db(conn)
    print(f"  [db] active={len(active)} skipped={len(skipped)}")

    batch = active[:MAX_SUBSCRIBERS_PER_RUN]
    if len(active) > len(batch):
        print(f"  [throttle] capped to {MAX_SUBSCRIBERS_PER_RUN}/run (free email quota). "
              f"{len(active)-len(batch)} deferred to next run.")

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    processed = sent = no_jobs = failed = 0

    for sub in batch:
        email = sub.get("Email Address", "")
        name = sub.get("Full Name", "")
        try:
            if already_sent_today_db(sub.get("Last Newsletter Sent")):
                print(f"  [skip] {name} <{email}> already sent today (idempotent).")
                continue
            print(f"  [..] {name} <{email}> | {sub.get('Primary Role','')} "
                  f"| {sub.get('_experience_years')}y | {sub.get('_location')}")

            if conn is None:
                raise RuntimeError("No DB connection (check SUPABASE_DB_URL).")

            candidates = search_matching_jobs(conn, sub, limit=15)
            print(f"       vector hits: {len(candidates)}")
            selected = evaluate_and_rank_jobs(sub, candidates)
            print(f"       agent picks: {len(selected)}")

            if selected:
                ok = send_newsletter_email(sub, selected)
                if ok:
                    if not DRY_RUN:
                        update_subscriber_writeback(conn, email, today_str,
                                                    f"Sent ({len(selected)} jobs matched)")
                    sent += 1
                    print("       ✅ sent.")
                else:
                    raise RuntimeError("email delivery failed after retries")
            else:
                if not DRY_RUN:
                    update_subscriber_writeback(conn, email, sub.get("Last Newsletter Sent") or None,
                                                "No relevant jobs found this week")
                no_jobs += 1
                print("       ⚠️ no relevant jobs.")
            processed += 1
            time.sleep(THROTTLE_SECONDS)  # Gemini 15 RPM guardrail
        except Exception as e:
            failed += 1
            print(f"       ❌ {email}: {e}")
            traceback.print_exc()
            try:
                if not DRY_RUN and conn is not None:
                    update_subscriber_writeback(conn, email, sub.get("Last Newsletter Sent") or None,
                                                f"Failed: {str(e)[:60]}")
            except Exception as we:
                print(f"       [writeback] failed: {we}")

    if conn is not None:
        conn.close()
    print(f"DONE. processed={processed} sent={sent} no_jobs={no_jobs} failed={failed}")


if __name__ == "__main__":
    main()
