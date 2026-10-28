# System Requirements Document (SRD)
## AI-Powered Personalized Job Newsletter System (Google Sheets Integration)

**Document Version:** 1.1  
**Status:** Draft / Technical Specification  
**Primary Integration Source:** Google Sheets (Subscriber Management)  

---

## 1. Executive Summary & Objectives

This document specifies the requirements for an automated, AI-driven weekly job newsletter system designed for a digital startup. The primary subscriber list is maintained in **Google Sheets**. Every week, an autonomous workflow reads subscriber profiles from Google Sheets, performs multi-tier candidate-job matching against recent job postings, generates personalized job recommendations using an AI Agent, delivers custom emails, and updates status tracking back in Google Sheets.

### Core Objectives
* **Google Sheets Integration:** Seamlessly read, validate, and process job seeker data directly from Google Sheets without manual intervention.
* **Precision Matching:** Combine deterministic filtering (experience, location) and vector search with AI semantic reasoning to achieve $>85\%$ match relevance.
* **Cost & Performance Efficiency:** Utilize a two-tier retrieval pipeline (Pre-filter + Vector Search + LLM Agent) to keep execution costs below **$0.003 USD per subscriber/week**.
* **Reliable Operations:** Execute weekly batch processing for up to 50,000 subscribers within a 4-hour window.

---

## 2. System Architecture & Workflow

```
   ┌────────────────────────────────────────────────────────┐
   │                    Google Sheets                       │
   │               (Subscriber Master List)                 │
   └──────────────────────────┬─────────────────────────────┘
                              │
                              │ 1. Weekly Fetch & Read (Google Sheets API)
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │                Ingestion & Cache Worker                │
   │           (Schema Validation & Pre-processing)         │
   └──────────────────────────┬─────────────────────────────┘
                              │
                              │ 2. Sync to Temp Cache / PostgreSQL
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │               Hybrid Matcher (PostgreSQL)              │
   │   - Step A: Hard SQL Filters (Exp, Location, Age)      │
   │   - Step B: Vector Similarity Search (pgvector)        │
   └──────────────────────────┬─────────────────────────────┘
                              │
                              │ 3. Top 15 Candidate Jobs per Subscriber
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │                 AI Reasoning Agent                     │
   │            (LangGraph / GPT-4o-mini)                   │
   │   - Skill gap analysis & final top 3-5 job selection   │
   │   - Personalized rationale generation                  │
   └──────────────────────────┬─────────────────────────────┘
                              │
                              │ 4. Structured Match Payload
                              ▼
   ┌────────────────────────────────────────────────────────┐
   │            Email Service & Writeback Engine            │
   │   - Dispatch email via Resend / SendGrid               │
   │   - Update "Last Sent Date" & "Status" in Google Sheet │
   └────────────────────────────────────────────────────────┘
```

---

## 3. Functional Requirements

### 3.1 Google Sheets Subscriber Ingestion
* **FR-1.1 (Sheet OAuth/Service Account Auth):** System must authenticate securely to Google Sheets API using a dedicated Service Account with read/write scopes.
* **FR-1.2 (Row Processing & Filtering):** The weekly job runner must read all rows in the designated Google Sheet where:
  * `Status` == `Active`
  * `Email` is valid and non-empty.
  * `Subscription` == `Weekly`.
* **FR-1.3 (Data Sanitization & Validation):**
  * Convert skill comma-separated strings into normalized array structures (e.g., `"React, TypeScript, Node.js"` $\rightarrow$ `["React", "TypeScript", "Node.js"]`).
  * Parse experience years into numerical values.
  * Validate work location preferences (`Remote`, `Hybrid`, `Onsite`).
* **FR-1.4 (Google Sheet Writeback):** After processing and sending the email, the system must update the corresponding row in Google Sheets:
  * Update `Last Newsletter Sent` date column.
  * Log execution status (e.g., `Sent`, `No Relevant Jobs Found`, `Failed - Invalid Email`).

### 3.2 Job Data Ingestion Pipeline
* **FR-2.1 (Job Fetching):** Ingest new job postings posted in the last 7 days from designated scrapers, job boards, or internal database APIs.
* **FR-2.2 (Embedding Generation):** Automatically generate 1536-dimensional vector embeddings (`text-embedding-3-small`) for all incoming job titles and descriptions upon job ingestion.
* **FR-2.3 (Job Store):** Store structured job details and vector embeddings in PostgreSQL with `pgvector`.

### 3.3 Multi-Tier Job Matching Engine
* **FR-3.1 (Tier 1 - Deterministic Pre-filtering):** Filter job candidates using SQL query constraints:
  * Job created timestamp $\ge \text{NOW}() - \text{INTERVAL } 7 \text{ days}$.
  * Candidate experience falls within job bounds ($\text{Min Exp} \le \text{Candidate Exp} \le \text{Max Exp} + 2$).
  * Location match (Exact city match for Onsite/Hybrid, or Global for Remote).
* **FR-3.2 (Tier 2 - Vector Similarity Search):**
  * Generate an embedding representation of the candidate profile from Google Sheet fields.
  * Perform cosine similarity search via `pgvector` to retrieve the top 15 candidate jobs per subscriber.
* **FR-3.3 (Tier 3 - AI Agent Reasoning & Final Selection):**
  * AI Agent evaluates the top 15 candidate jobs for each candidate.
  * Conducts skill-gap evaluation (differentiating core requirements from nice-to-haves).
  * Selects the **top 3 to 5 best matching jobs**.
  * Drafts a 1–2 sentence personalized reasoning statement explaining *why* this job was recommended for the subscriber.

### 3.4 Email Rendering & Delivery
* **FR-4.1:** Render candidate-specific HTML templates populated with selected jobs, apply URLs, match scores, and custom AI rationales.
* **FR-4.2:** Transmit emails using bulk transactional email services (Resend / SendGrid API) with rate-limiting and retry logic.
* **FR-4.3:** Automatically append unsubscribing options that update the subscriber's `Status` in Google Sheets to `Unsubscribed`.

---

## 4. Google Sheet & Database Schema Specifications

### 4.1 Required Google Sheet Column Schema

| Column Name | Data Type | Required | Example Value | Description |
| :--- | :--- | :--- | :--- | :--- |
| `Subscriber ID` | String / UUID | Yes | `SUB-10294` | Unique key for the subscriber |
| `Full Name` | String | Yes | `Jane Doe` | Subscriber's name |
| `Email Address` | String | Yes | `jane.doe@example.com` | Email destination |
| `Primary Role` | String | Yes | `Senior Frontend Engineer` | Target role title |
| `Years of Experience` | Integer | Yes | `5` | Total relevant experience |
| `Key Skillsets` | String | Yes | `React, TypeScript, Next.js, Tailwind` | Comma-separated list of skills |
| `Work Preference` | String | Yes | `Remote` | `Remote`, `Hybrid`, `Onsite` |
| `Preferred Location` | String | Conditional | `Chicago, IL` | Required if Hybrid/Onsite |
| `Status` | String | Yes | `Active` | `Active`, `Paused`, `Unsubscribed` |
| `Last Newsletter Sent` | Date / Time | Auto-updated | `2026-10-02` | Set by AI workflow post-execution |
| `Execution Notes` | String | Auto-updated | `Sent (4 jobs matched)` | Audit feedback from system |

### 4.2 Database Schema (PostgreSQL Working Cache)

```sql
-- Installed Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Job Listings Table
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(200) NOT NULL,
    company VARCHAR(150) NOT NULL,
    location VARCHAR(150),
    work_style VARCHAR(50) CHECK (work_style IN ('Remote', 'Hybrid', 'Onsite')),
    min_experience INT DEFAULT 0,
    max_experience INT DEFAULT 30,
    required_skills TEXT[] NOT NULL,
    description_text TEXT NOT NULL,
    apply_url TEXT NOT NULL,
    embedding VECTOR(1536),
    posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- HNSW Vector Index for Instant Semantic Matching
CREATE INDEX idx_jobs_embedding ON jobs 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Local Cache Table for Subscribers Synced from Google Sheets
CREATE TABLE subscribers_cache (
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
    profile_embedding VECTOR(1536),
    last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## 5. Non-Functional Requirements (NFRs)

* **Performance & Scalability:**
  * System must process 1,000 subscribers per 5-minute processing interval to prevent Google Sheets API quota limits ($600\text{ requests/min}$).
  * `pgvector` HNSW index latency must complete similarity queries in $< 30\text{ ms}$.
* **API Cost Constraints:**
  * System token optimization must restrict total LLM costs ($gpt-4o-mini$ or $Claude\ 3.5\ Haiku$) to under **$3.00 USD per 1,000 processed subscribers**.
* **Reliability & Idempotency:**
  * Execution must be idempotent. In the event of a system failure, re-executing the workflow will check the `Last Newsletter Sent` field in Google Sheets to avoid sending duplicate emails.
* **Privacy & Compliance:**
  * Personally Identifiable Information (PII) such as full names and email addresses must be stripped before sending profile payloads to external LLM APIs for matching.

---

## 6. Implementation Roadmap

| Phase | Focus Area | Deliverables | Target Timeframe |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Google Sheets & DB Sync | Google Sheets API setup, row reader, validation engine, PostgreSQL schema setup | Weeks 1–2 |
| **Phase 2** | Job Ingestion & Vectorizing | Scraping/API job loader, OpenAI vector embedding generation, HNSW index configuration | Weeks 3–4 |
| **Phase 3** | AI Agent & Matching Logic | SQL hybrid filtering, vector retrieval, LangGraph agent prompt engineering, JSON response parser | Weeks 5–6 |
| **Phase 4** | Emailing & Writeback | HTML email renderer, Resend API integration, Google Sheets writeback logger | Weeks 7–8 |
| **Phase 5** | End-to-End Orchestration | Temporal/Cron scheduling, failure handling, load testing with 10k mock rows | Weeks 9–10 |