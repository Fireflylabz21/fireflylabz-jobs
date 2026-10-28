-- Supabase / Postgres schema for $0 job newsletter (pgvector 768-dim = gemini-embedding-001 truncated)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    work_style VARCHAR(50) CHECK (work_style IN ('Remote', 'Hybrid', 'Onsite')),
    min_experience INT DEFAULT 0,
    max_experience INT DEFAULT 30,
    required_skills TEXT[] NOT NULL DEFAULT '{}',
    description_text TEXT NOT NULL,
    apply_url TEXT NOT NULL,
    embedding VECTOR(768),
    posted_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_jobs_embedding
    ON jobs USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs (is_active) WHERE is_active = TRUE;

-- Tally form https://tally.so/r/D4r5xp source of truth (replaces Google Sheets).
-- Fields: Full Name | Email Address | Phone Number | Primary Skillsets
-- | Secondary Skillsets | Years of Experience | Current Company
-- | Current CTC | Notice Period | Current Location | Expected Location | Resume
CREATE TABLE IF NOT EXISTS subscribers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    email CITEXT UNIQUE NOT NULL,
    phone_number TEXT DEFAULT '',
    primary_skillsets TEXT NOT NULL DEFAULT '',
    secondary_skillsets TEXT DEFAULT '',
    years_experience INT DEFAULT 0,
    current_company TEXT DEFAULT '',
    current_ctc TEXT DEFAULT '',
    notice_period TEXT DEFAULT '',
    current_location TEXT DEFAULT '',
    expected_location TEXT DEFAULT '',
    resume_url TEXT DEFAULT '',
    tally_response_id TEXT UNIQUE,
    status TEXT DEFAULT 'Active',
    last_sent DATE,
    notes TEXT DEFAULT '',
    unsubscribed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscribers_status ON subscribers (status);
CREATE INDEX IF NOT EXISTS idx_subscribers_last_sent ON subscribers (last_sent);

-- Optional local cache of subscribers synced from Google Sheets (SRD 4.2)
CREATE TABLE IF NOT EXISTS subscribers_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_sheet_row INT NOT NULL,
    sheet_subscriber_id VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(150),
    primary_role VARCHAR(150),
    years_experience INT,
    skills TEXT[],
    work_preference VARCHAR(50),
    preferred_location VARCHAR(150),
    profile_embedding VECTOR(768),
    last_synced_at TIMESTAMPTZ DEFAULT NOW()
);

-- Unsubscribe support ($0): soft-delete via status='Unsubscribed' (audit + re-subscribe).
-- Run once in Supabase SQL editor if table already exists:
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMPTZ;
-- Drip queue: shard 300/day Brevo cap across Mon-Thu ($0 scale to ~2000 subs).
-- Run in Supabase SQL editor once:
CREATE TABLE IF NOT EXISTS email_queue (
    email CITEXT NOT NULL,
    week DATE NOT NULL,
    priority INT DEFAULT 0,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','skipped')),
    attempts INT DEFAULT 0,
    last_error TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    PRIMARY KEY (email, week)
);
CREATE INDEX IF NOT EXISTS idx_queue_week_status ON email_queue (week, status, priority DESC);
-- Free-tier hygiene: run weekly before pipeline
-- DELETE FROM jobs WHERE posted_at < NOW() - INTERVAL '14 days';

-- Scraper chunk run tracking ($0/month monitoring)
-- Run: insert after each chunk completes; query to review progress
CREATE TABLE IF NOT EXISTS scraper_chunk_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_date DATE NOT NULL,           -- which day this chunk covered
    day_of_week TEXT NOT NULL,          -- Monday, Tuesday, etc.
    source TEXT NOT NULL,               -- remoteok,arbeitnow,naukri,linkedin
    roles TEXT[] NOT NULL,              -- which role titles were searched
    locations TEXT[] NOT NULL,          -- which cities were searched
    experience_bands TEXT[] NOT NULL,   -- ENTRY,MID_JUNIOR,etc.
    jobs_found INT DEFAULT 0,           -- total jobs retrieved from source
    jobs_new INT DEFAULT 0,             -- new jobs upserted to DB
    jobs_dup INT DEFAULT 0,             -- jobs already in DB (deduped)
    runtime_seconds INT DEFAULT 0,      -- how long the scrape took
    status TEXT DEFAULT 'completed' CHECK (status IN ('running','completed','failed')),
    error_message TEXT DEFAULT '',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_scraper_chunk_runs_date ON scraper_chunk_runs (chunk_date, day_of_week);
CREATE INDEX IF NOT EXISTS idx_scraper_chunk_runs_status ON scraper_chunk_runs (status);
