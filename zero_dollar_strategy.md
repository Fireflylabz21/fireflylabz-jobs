# Zero-Dollar ($0/month) Architecture & Operational Strategy
## AI-Powered Job Newsletter System

---

## 1. Executive Summary

Building an automated, AI-driven job newsletter does not require expensive cloud infrastructure or costly LLM API subscriptions. By leveraging generous **Free Tier offerings** across modern developer tools, AI APIs, database hosting, and email providers, you can run this entire system for **$0/month** for up to **1,000–3,000 active weekly subscribers**.

This document outlines the zero-cost technology stack, architectural choices, quota management strategies, and step-by-step implementation plan.

---

## 2. Zero-Dollar Tech Stack Matrix

| Function / Component | Free Service Selected | Free Tier Quota / Allowance | Cost Strategy & Workaround |
| :--- | :--- | :--- | :--- |
| **Subscriber Management** | **Google Sheets** | Unlimited rows, 60 API requests/min | Native Google Sheet integration via standard `@gmail.com` Google Cloud Service Account. |
| **Database & Vector Store** | **Supabase Free Tier** | 500 MB PostgreSQL, `pgvector` enabled | Store active jobs and profile vector embeddings in a single free PostgreSQL instance. |
| **Vector Embeddings** | **Google AI Studio** (`text-embedding-004`) | 1,500 Requests per Minute (RPM), Free | Generate 768-dimensional embeddings for candidates and jobs with zero cost. |
| **AI Reasoning Agent** | **Google AI Studio** (`gemini-1.5-flash`) or **Groq Cloud** (`llama-3.1-8b`) | Gemini: 15 RPM, 1M Tokens/min, 1,500 Requests/day; Groq: 30 RPM, 14,400 Requests/day | Evaluate top matches and write personalized bullet points completely free using fast, low-latency models. |
| **Orchestration & Cron Jobs**| **GitHub Actions** | 2,000 free build minutes/month for public/private repos | Run a weekly Python execution script on schedule (`cron`). Execution takes ~5–10 mins/week ($< 50\text{ mins/month}$). |
| **Email Delivery** | **Brevo (Sendinblue)** or **Resend** | Brevo: 300 emails/day ($9,000\text{/month}$); Resend: 3,000 emails/month | Batch email delivery to stay under daily sending limits. |

---

## 3. System Flow in a $0 Budget Constraints Environment

```
 ┌──────────────────────────────────────────────────────────────┐
 │                      Google Sheets API                       │
 │      Reads Active Subscribers (Free Service Account)         │
 └──────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │                  GitHub Actions Workflow                     │
 │          (Runs Python Script Weekly for ~5 Minutes)          │
 └───────┬──────────────────────────────────────────────┬───────┘
         │                                              │
         ▼                                              ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│       Supabase (Free Postgres)  │   │     Google AI Studio API      │
│  - SQL Hard Filters (Exp, City) │   │  - `text-embedding-004` (Free)  │
│  - `pgvector` Cosine Similarity │   │  - `gemini-1.5-flash` Reasoning │
└────────────────┬────────────────┘   └────────────────┬────────────────┘
                 │                                     │
                 └──────────────────┬──────────────────┘
                                    │
                                    ▼
 ┌──────────────────────────────────────────────────────────────┐
 │                 Brevo / Resend Free API                      │
 │     Sends Personalized Emails (Throttled Rate Batches)       │
 └──────────────────────────────┬───────────────────────────────┘
                                │
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │                      Google Sheets API                       │
 │         Updates 'Last Sent' Status in Google Sheets          │
 └──────────────────────────────────────────────────────────────┘
```

---

## 4. Deep-Dive Tooling & Zero-Cost Configuration

### 4.1 Subscriber Store: Google Sheets API
* **Cost:** $0.00
* **Setup:** Create a free Google Cloud Platform (GCP) project, enable the **Google Sheets API**, and create a **Service Account**.
* **Credentials:** Export the Service Account JSON key and add it as an encrypted Secret (`GCP_SERVICE_ACCOUNT_KEY`) in GitHub Actions.

### 4.2 Database & Vector Search: Supabase (`pgvector`)
* **Cost:** $0.00
* **Setup:** Create a free project at [supabase.com](https://supabase.com). Enable the `vector` extension in PostgreSQL:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
* **Embedding Model Calibration:** Configure `pgvector` to store 768-dimensional vectors matching Google's `text-embedding-004` model:
  ```sql
  CREATE TABLE jobs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      title TEXT NOT NULL,
      company TEXT NOT NULL,
      location TEXT,
      work_style VARCHAR(50),
      min_experience INT DEFAULT 0,
      description_text TEXT NOT NULL,
      apply_url TEXT NOT NULL,
      embedding VECTOR(768),
      posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );

  -- Index for ultra-fast vector searches
  CREATE INDEX ON jobs USING hnsw (embedding vector_cosine_ops);
  ```

### 4.3 Embeddings & Reasoning Agent: Google AI Studio
* **Cost:** $0.00
* **APIs Used:**
  1. `text-embedding-004`: Converts profile text and job descriptions into vector embeddings.
  2. `gemini-1.5-flash`: Analyzes job-candidate alignment, selects top 3–5 opportunities, and generates personalized text.
* **Throttling Logic:** Implement a 4-second delay (`time.sleep(4)`) between subscriber iterations to comply with the 15 Requests Per Minute (RPM) free limit.

### 4.4 Automation Orchestrator: GitHub Actions Cron
* **Cost:** $0.00
* **Setup:** Create a `.github/workflows/weekly_newsletter.yml` file in your repository:
  ```yaml
  name: Weekly AI Job Newsletter

  on:
    schedule:
      # Run every Sunday at 08:00 UTC
      - cron: '0 8 * * 0'
    workflow_dispatch: # Allows manual triggering

  jobs:
    process-newsletter:
      runs-on: ubuntu-latest
      steps:
        - name: Check out repo
          uses: actions/checkout@v4

        - name: Set up Python
          uses: actions/setup-python@v5
          with:
            python-version: '3.11'

        - name: Install dependencies
          run: pip install google-generativeai psycopg2-binary gspread google-auth resend

        - name: Run Newsletter Generator
          env:
            GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
            SUPABASE_DB_URL: ${{ secrets.SUPABASE_DB_URL }}
            GCP_SERVICE_ACCOUNT_KEY: ${{ secrets.GCP_SERVICE_ACCOUNT_KEY }}
            RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
          run: python main.py
  ```

### 4.5 Email Dispatch Service: Brevo or Resend
* **Cost:** $0.00
* **Strategy:**
  * **Brevo Free Tier:** Offers **300 emails/day** ($9,000\text{ emails/month}$).
  * **Resend Free Tier:** Offers **3,000 emails/month** ($100\text{ emails/day}$).
  * **Batch Execution:** If subscriber list exceeds 300, the script processes only 300 candidates per day over consecutive scheduled runs.

---

## 5. Cost-Optimization Guardrails & Limits

1. **Database Size Management:**
   * Supabase free tier limits storage to 500 MB.
   * **Cleanup Strategy:** Automatically delete jobs older than 14 days to keep storage consumption under 50 MB:
     ```sql
     DELETE FROM jobs WHERE posted_at < NOW() - INTERVAL '14 days';
     ```

2. **API Rate Limit Compliance:**
   * Gemini 1.5 Flash free rate limit: 15 Requests/Min (RPM) and 1,500 Requests/Day (RPD).
   * **Batching Strategy:** Group 3–5 candidates into a single prompt payload to evaluate multiple subscribers per API call if scaling is needed.

3. **Memory & Execution Time:**
   * GitHub Actions allows up to 6 hours per job run, which is more than enough time to process thousands of candidates with built-in sleep pauses.

---

## 6. Implementation Checklist

- [ ] Create Google Sheet with subscriber columns and share edit access with a GCP Service Account.
- [ ] Spin up a free Supabase PostgreSQL database and run initial SQL schemas.
- [ ] Obtain a free API Key from Google AI Studio ([aistudio.google.com](https://aistudio.google.com)).
- [ ] Set up a free email sending domain on Brevo or Resend.
- [ ] Write the Python processing script integrating `gspread`, `psycopg2`, and `google-generativeai`.
- [ ] Commit code to GitHub and save API keys under **Settings $\rightarrow$ Secrets and variables $\rightarrow$ Actions**.
- [ ] Execute a manual trigger run on GitHub Actions to test end-to-end delivery.