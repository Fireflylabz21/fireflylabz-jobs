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
    parser.add_argument("--check-only", action="store_true",
                        help="Only check matching, no sends")
    args = parser.parse_args()

    # Validate environment
    missing = []
    if not os.getenv("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if not os.getenv("SUPABASE_DB_URL"):
        missing.append("SUPABASE_DB_URL")
    if missing:
        raise ValueError(f"Missing required env vars: {', '.join(missing)}")

    print(f"DRY_RUN={DRY_RUN}")
    print(f"SOURCE=supabase.subscribers")

    result = run_ingest_jobs_agent()
    print(f"\nResult: {result}")


if __name__ == "__main__":
    import os
    main()