"""Sunday step: ingest fresh jobs + sync Tally + enqueue this week's drip queue.
Usage: python enqueue_week.py [--jobs-limit 30]
Then Mon-Thu: python send_batch.py drains 280/day (Brevo $0 cap).
"""
import argparse
from db import enqueue_week, get_db_connection, queue_stats, week_monday

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs-limit", type=int, default=30)
    args = ap.parse_args()

    # keep imports lazy so --help works without keys
    import ingest_jobs
    import sync_tally

    print("Sunday enqueue: ingest -> sync -> queue")
    jobs = ingest_jobs.fetch_all(args.jobs_limit)
    ins, skip = ingest_jobs.upsert_jobs(jobs)
    print(f"  [jobs] fetched={len(jobs)} inserted={ins} dupes={skip}")

    print("  [tally] syncing...")
    sync_tally.main()

    conn = get_db_connection()
    week = week_monday()
    queued, total = enqueue_week(conn, week)
    stats = queue_stats(conn, week)
    conn.close()
    print(f"  [queue] week={week} queued={queued}/{total} stats={stats}")
    print("DONE. Mon-Thu send_batch.py will drain pending by priority.")
