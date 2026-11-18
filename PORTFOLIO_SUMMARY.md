# Fireflylabz Job Alerts - Portfolio Documentation

## App Overview

Fireflylabz Job Alerts is a fully automated weekly AI job newsletter platform that scrapes job listings from multiple sources, matches them to subscriber preferences using AI, and delivers personalized job alerts via email. The system operates on a $0/month cost structure using free-tier services.
## Architecture

The system consists of three main agents:

1. **ScraperAgent** (Tier 2): LangGraph-based orchestrator that scrapes jobs from multiple sources on a day-of-week schedule, deduplicates by apply_url, and upserts to Supabase jobs table.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Scraping | BeautifulSoup4, requests |
| AI/ML | Google Generative AI (Gemini Flash), pgvector |
| Orchestration | LangGraph, LangChain |
## Data Sources

### Job Boards Scraped
1. **RemoteOK** - Remote job board
2. **Arbeitnow** - German job board
3. **BuiltIn** - Via Indeed API
4. **Greenhouse** - Company career boards (AI companies)
5. **Direct Company Sites** - Top AI companies careers pages

### Subscriber Data
### Pipeline Flow

```
Weekly GitHub Action → Scrape Jobs (daily cron) → Ingest & Match → Send Emails
     │                      │                │
     ▼                      ▼                ▼
Daily at 1AM UTC    Day-of-week chunks   Top 3-5 jobs/sub
   │                      │                │
   ▼                      ▼                ▼
ScraperAgent        Gemini Flash       Brevo/Resend
## Key Design Decisions

- **DB-first approach**: Query existing jobs before scraping new ones (ingest_jobs_agent.py)
- **Chunked execution**: Day-of-week scheduling prevents API overload
- **Multiple fallbacks**: API failures → next source → email fallback
- **Environment-driven**: Local .env for development, GitHub Secrets for production
- **Cost optimization**: Free-tier awareness (15 RPM Gemini, 300/day Brevo, 500MB Supabase)
- **Idempotent design**: Safe re-execution without side effects or duplicates
   │                      │                │
   ▼                      ▼                ▼
### AI Concepts Demonstrated

- **LangGraph orchestration**: State machines for complex workflows
- **Prompt engineering**: Structured LLM calls with forced JSON output
- **Vector search**: pgvector integration for semantic similarity (768-dim embeddings)
- **Multi-step pipelines**: ETL with branching logic and fallbacks
- **Skill gap analysis**: Separating core requirements vs nice-to-haves
- **Output formatting**: Forced JSON with safe fallbacks and PII stripping
Upsert to DB       Skill-gap analysis   Email templates
```
### Portfolio Value

- **Built** automated AI job newsletter platform processing 100+ subscribers weekly
- **Designed** LangGraph-based scraper orchestrator with day-of-week chunk scheduling
- **Implemented** pgvector-powered job matching using Gemini Flash LLM rankings
- **Created** idempotent pipeline with deduplication by apply_url and last-sent tracking
- **Integrated** 4+ job board sources with automatic fallback on failures
- **Optimized** for $0/month operation using free-tier services (Brevo 300/day, Supabase)
- **Architected** multi-agent system: scraper → matcher → emailer with clear separation
- **Deployed** via GitHub Actions with CI/CD pipelines and environment management

### GitHub Repository
https://github.com/Fireflylabz21/fireflylabz-jobs

### Key Files
- scraper_agent.py - LangGraph orchestrator
- chunk_dispatcher.py - Day scheduling
- ingest_jobs_agent.py - Matching & emailing
- agent.py - Gemini Flash ranking
- db.py - Supabase/pgvector integration
---

## Paragraph-Level Summary

Fireflylabz Job Alerts is an automated Python-powered platform that scrapes job listings from multiple boards, matches them to subscriber preferences using Google's Gemini Flash LLM and pgvector similarity search, and delivers personalized weekly newsletters via Brevo email—all operating on a $0/month budget through strategic use of free-tier services. The architecture features a three-tier agent system: a LangGraph-based scraper orchestrator with day-of-week chunk scheduling, a DB-first ingestion agent that ranks matches and sends emails, and a Tier 3 AI reasoning agent that performs skill-gap analysis and generates personalized job rationales. Key design decisions include DB-first processing to avoid redundant scraping, chunked execution for API rate-limit management, multiple fallbacks for API failures, and environment-driven configuration for local development versus GitHub Actions production. The system processes approximately 100 subscribers weekly, matching each to 3-5 relevant jobs using vector similarity search, and demonstrates expertise in LangGraph orchestration, vector search implementation, prompt engineering with forced JSON output, and cost-optimized AI application development.

---

*Document generated for portfolio and resume purposes. For technical details, see the GitHub repository: https://github.com/Fireflylabz21/fireflylabz-jobs*
- emailer.py - Branded email templates

### Tech Stack
Python, LangGraph, Gemini Flash, pgvector, Supabase, Brevo

### Resume Bullet Points
- Built automated AI job newsletter platform processing 100+ subscribers weekly at $0/month cost
- Designed LangGraph-based scraper orchestrator with day-of-week chunk scheduling
- Implemented pgvector-powered job matching using Gemini Flash LLM for skill-gap analysis and ranking
- Created idempotent pipeline with deduplication by apply_url and last-sent date tracking
- Integrated 4+ job board sources with automatic fallback on API failures
- Optimized for $0/month operation using free-tier services (Brevo 300/day, Supabase 500MB, Gemini 15 RPM)
- Architected three-tier agent system: scraper → matcher → emailer with clear separation of concerns
- Deployed via GitHub Actions CI/CD with environment management (local .env vs GitHub Secrets)
- **Source**: Tally (form responses) → Synced to Supabase
- **Fields**: Primary role, experience years, location, skills, work preference
- **Operations**: Active filtering, last_sent date tracking
| Database | PostgreSQL via Supabase with pgvector |
| Email | Brevo (primary), Resend (fallback) |
| Config | python-dotenv |
| CI/CD | GitHub Actions |
| Scheduling | Cron + day-of-week logic |
2. **IngestJobsAgent** (Tier 1): DB-first approach that matches jobs to subscribers, ranks with Gemini Flash, and sends emails; triggers scraper when no matches found.

3. **Tier 3 AI Reasoning Agent**: Handles job matching with skill-gap analysis, top-3-5 selection with personalized rationale generation, and forced JSON output.