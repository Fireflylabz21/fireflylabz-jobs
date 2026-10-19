# 🔥 FireflyLabz AI Job Newsletter — $0/month

Weekly personalized job emails: `Tally -> Supabase pgvector -> Gemini match+rank -> Brevo/Resend`.

Live: 3 subs, 7 real India jobs, Brevo 300/day primary + Resend fallback, dark-mode branded template.

## Quickstart (local, VS Code)
1. `python -m venv venv` + activate, `pip install -r requirements.txt`
2. Copy `.env.example` → `.env`, fill:
   - `GEMINI_API_KEY` ([AI Studio](https://aistudio.google.com))
   - `SUPABASE_DB_URL` (pooler `aws-0-ap-southeast-1.pooler.supabase.com:6543`, Transaction mode)
   - `TALLY_API_KEY` + `TALLY_FORM_ID=QKgdWX`
   - `EMAIL_PROVIDER=brevo`, `BREVO_API_KEY` (`xkeysib-...`), `BREVO_SENDER_EMAIL` (verified in Brevo Senders)
   - `RESEND_API_KEY` (fallback), `FROM_EMAIL`
   - Brand `LOGO_LIGHT/DARK/BANNER_URL` (public https), `UNSUBSCRIBE_BASE_URL/SECRET` (optional)
3. Supabase SQL Editor → run `schema.sql` (enables `vector`, 768-dim HNSW).
   If table exists: `ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMPTZ;`
4. Test: `python db_check.py` → `DB CONNECT OK`
   `python sync_tally.py` → `python ingest_jobs.py --limit 30` (or `python ingest_real_jobs.py` for curated)
   `DRY_RUN=true python main.py` → `python -c "from emailer import preview_email; preview_email()"` → open `preview_email.html`
5. Live: `python main.py` (`processed/sent/no_jobs/failed`).

## Deploy (GitHub Actions, Sundays 08:00 UTC)
1. `git init && git add . && git commit -m "live"` — NEVER commit `.env` / `*.json` (gitignored).
   `gh repo create fireflylabz-jobs --public --source=. --push`
2. Repo Settings → Secrets and variables → Actions → add:
   `GEMINI_API_KEY`, `GEMINI_LLM_MODEL`, `GEMINI_EMBED_MODEL`,
   `SUPABASE_DB_URL`, `SUPABASE_URL`, `SUPABASE_KEY`,
   `EMAIL_PROVIDER=brevo`, `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME`,
   `RESEND_API_KEY`, `FROM_EMAIL`,
   `TALLY_API_KEY`, `TALLY_FORM_ID`,
   `LOGO_LIGHT_URL`, `LOGO_DARK_URL`, `BANNER_URL`, `BRAND_WEBSITE`,
   `UNSUBSCRIBE_BASE_URL`, `UNSUBSCRIBE_SECRET`
3. Actions → Run Weekly Job Newsletter → Run workflow → check `sent=N`.
   Cron: `0 8 * * 0` runs `ingest_jobs.py → sync_tally.py → main.py`.

## Unsubscribe ($0)
- Footer auto: signed link if `UNSUBSCRIBE_BASE_URL` set, else `Reply STOP`.
- Host `unsubscribe_page.py` on Streamlit Cloud (Secrets `SUPABASE_DB_URL`, `UNSUBSCRIBE_SECRET`), set BASE URL.
- CLI: `python manage_subscribers.py list-unsubscribed | unsubscribe a@b.com | resubscribe a@b.com | delete a@b.com` (GDPR only).

## Files
`main.py` pipeline · `sync_tally.py` Tally→DB · `ingest_jobs.py` auto (RemoteOK+Arbeitnow) · `ingest_real_jobs.py` curated India · `matcher.py` SQL+pgvector+city rank · `agent.py` Gemini Flash rank · `emailer.py` Brevo/Resend branded · `embeddings.py` 768d · `db.py` · `config.py` · `schema.sql` · `unsubscribe.py` · `manage_subscribers.py` · `unsubscribe_page.py`
Legacy backup (unused): `sheets_client.py`, `db_supabase_client.py`, `seed_jobs.py`.
