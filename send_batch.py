"""Drip sender: Mon-Thu batches of BATCH_LIMIT (default 280, Brevo 300/day buffer).
Usage: python send_batch.py [--limit 280] [--week YYYY-MM-DD]
Respects: queue priority, idempotency (last_sent), Gemini 15 RPM throttle.
Run after: enqueue_week.py (Sundays). Safe to re-run (pending only).
"""
import argparse
import datetime
import time
import traceback

from config import BATCH_LIMIT, DRY_RUN, JOB_LOOKBACK_DAYS, THROTTLE_SECONDS, validate_env
from db import (
    cleanup_old_jobs,
    fetch_batch,
    get_db_connection,
    mark_queued,
    queue_stats,
    update_subscriber_writeback,
    week_monday,
)
from matcher import search_matching_jobs
from agent import evaluate_and_rank_jobs
from emailer import send_newsletter_email


def brevo_sent_today(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM subscribers WHERE last_sent = CURRENT_DATE;")
        return int(cur.fetchone()["c"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=BATCH_LIMIT)
    ap.add_argument("--week", type=str, default="")
    args = ap.parse_args()
    week = args.week or week_monday()
    limit = args.limit

    print(f"Starting drip batch: week={week} limit={limit} DRY_RUN={DRY_RUN}")
    missing = validate_env(strict=False)
    if missing:
        print(f"  [warn] missing env: {missing}")

    conn = get_db_connection()
    try:
        cleanup_old_jobs(conn, JOB_LOOKBACK_DAYS)
    except Exception as e:
        print(f"  [db] cleanup note: {e}")

    # Brevo 300/day guard: stop before API 402s
    try:
        used = brevo_sent_today(conn)
        remaining = 300 - used
        if remaining <= 0:
            print(f"  [cap] Brevo daily cap reached (sent_today={used}). Exiting, retry tomorrow.")
            print(f"DONE. processed=0 sent=0")
            return
        if limit > remaining - 20:  # 20 buffer
            limit = max(0, remaining - 20)
            print(f"  [cap] trimmed batch to {limit} (sent_today={used}, buffer 20).")
    except Exception as e:
        print(f"  [cap] check skipped: {e}")

    batch = fetch_batch(conn, week, limit)
    stats = queue_stats(conn, week)
    print(f"  [queue] week={week} stats={stats} batch={len(batch)}")
    if not batch:
        print("DONE. processed=0 sent=0 (queue drained)")
        return

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    processed = sent = no_jobs = failed = 0
    for sub in batch:
        email = sub.get("Email Address", "")
        name = sub.get("Full Name", "")
        try:
            print(f"  [..] {name} <{email}> | {sub.get('Primary Role','')}")
            candidates = search_matching_jobs(conn, sub, limit=15)
            selected = evaluate_and_rank_jobs(sub, candidates)
            print(f"       hits={len(candidates)} picks={len(selected)}")
            if selected:
                ok = send_newsletter_email(sub, selected)
                if ok:
                    if not DRY_RUN:
                        update_subscriber_writeback(conn, email, today_str,
                                                    f"Sent ({len(selected)} jobs matched)")
                        mark_queued(conn, email, week, "sent")
                    sent += 1
                    print("       sent.")
                else:
                    raise RuntimeError("email delivery failed after retries")
            else:
                if not DRY_RUN:
                    mark_queued(conn, email, week, "skipped")
                    update_subscriber_writeback(conn, email, sub.get("Last Newsletter Sent") or None,
                                                "No relevant jobs found this week")
                no_jobs += 1
                print("       no relevant jobs.")
            processed += 1
            time.sleep(THROTTLE_SECONDS)
        except Exception as e:
            failed += 1
            print(f"       FAILED {email}: {e}")
            traceback.print_exc(limit=2)
            try:
                if not DRY_RUN:
                    mark_queued(conn, email, week, "failed", str(e))
                    update_subscriber_writeback(conn, email, sub.get("Last Newsletter Sent") or None,
                                                f"Failed: {str(e)[:60]}")
            except Exception as we:
                print(f"       [writeback] failed: {we}")
    conn.close()
    print(f"DONE. processed={processed} sent={sent} no_jobs={no_jobs} failed={failed}")


if __name__ == "__main__":
    main()
