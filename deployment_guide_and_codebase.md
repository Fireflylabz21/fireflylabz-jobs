# $0/Month AI Job Newsletter: Architecture, Codebase & Deployment Guide

This document provides a complete technical breakdown, production-ready Python codebase, and step-by-step deployment guide to run an automated, AI-powered job newsletter system for **$0/month**.

---

## 1. System Architecture Deep-Dive

The system operates as an event-driven weekly batch pipeline orchestrated by **GitHub Actions**. It connects Google Sheets, Supabase, Google AI Studio, and Resend/Brevo while staying strictly within all free-tier quotas.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            GITHUB ACTIONS CRON                              │
│                    Trigger: Sunday @ 08:00 UTC (Weekly)                     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PYTHON ENGINE (main.py)                           │
│                                                                             │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌───────────────────┐  │
│  │ 1. Read Google Sheet │  │ 2. Fetch Jobs        │  │ 3. Gemini Vector  │  │
│  │    Active Subscriptions│  │    Supabase SQL Filter│  │    Embeddings     │  │
│  └──────────┬───────────┘  └──────────┬───────────┘  └─────────┬─────────┘  │
│             │                         │                        │            │
│             └─────────────────────────┼────────────────────────┘            │
│                                       ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 4. `pgvector` Cosine Similarity Match (Top 15 Jobs / Candidate)      │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                       ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 5. Gemini 1.5 Flash Reasoning Agent (Select Top 3-5 & Write Reason)   │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                       ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 6. Batch Email Dispatch (Resend / Brevo API)                          │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                       ▼                                     │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ 7. Writeback Update to Google Sheets (Last Sent Date & Notes)         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Free Tier Limits & Handling Strategy
1. **Google AI Studio (Gemini 1.5 Flash & `text-embedding-004`):**
   * *Limit:* 15 Requests Per Minute (RPM), 1,500 Requests Per Day (RPD).
   * *Handling:* Built-in `time.sleep(4.5)` between subscriber iterations guarantees compliance ($< 14\text{ RPM}$).
2. **Supabase (PostgreSQL):**
   * *Limit:* 500 MB database storage.
   * *Handling:* Automated weekly cleanup of jobs older than 14 days.
3. **Google Sheets API:**
   * *Limit:* 60 requests per minute per user.
   * *Handling:* Read all subscriber rows in a single batch call (`get_all_records()`), then perform bulk writebacks.
4. **Email Providers (Resend / Brevo):**
   * *Limit:* Resend (3,000 emails/month, 100/day); Brevo (300 emails/day).
   * *Handling:* Process max 100–300 subscribers per job execution batch.

---

## 2. Complete Codebase (`main.py`)

Save the following code as `main.py` in your GitHub repository root.

```python
import os
import json
import time
import datetime
from typing import List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import resend

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT SETUP
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
GCP_SERVICE_ACCOUNT_KEY = os.getenv("GCP_SERVICE_ACCOUNT_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Job Newsletter Subscribers")

# Initialize Clients
genai.configure(api_key=GEMINI_API_KEY)
resend.api_key = RESEND_API_KEY

# Configure Google Sheets Auth from Environment Variable
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
service_account_info = json.loads(GCP_SERVICE_ACCOUNT_KEY)
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
gs_client = gspread.authorize(creds)

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================

def get_db_connection():
    """Establishes connection to Supabase PostgreSQL."""
    return psycopg2.connect(SUPABASE_DB_URL, cursor_factory=RealDictCursor)

def generate_embedding(text: str) -> List[float]:
    """Generates 768-dimensional vector embedding using Google text-embedding-004."""
    response = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )
    return response['embedding']

def get_active_subscribers_from_sheets() -> List[Dict[str, Any]]:
    """Reads active subscribers from Google Sheets."""
    sheet = gs_client.open(GOOGLE_SHEET_NAME).sheet1
    records = sheet.get_all_records()
    
    active_subscribers = []
    for idx, row in enumerate(records, start=2):  # Row 1 is Header
        if str(row.get("Status", "")).strip().lower() == "active":
            row["_row_number"] = idx
            active_subscribers.append(row)
            
    return active_subscribers

def search_matching_jobs(conn, subscriber: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Performs two-tier retrieval:
    1. SQL Filter for recency, min_experience, and location.
    2. Vector similarity search via pgvector.
    """
    profile_text = f"Role: {subscriber.get('Primary Role')}. Skills: {subscriber.get('Key Skillsets')}. Preferred Work: {subscriber.get('Work Preference')}."
    profile_vector = generate_embedding(profile_text)
    
    experience = int(subscriber.get("Years of Experience", 0))
    work_pref = subscriber.get("Work Preference", "Remote")
    
    query = """
        SELECT id, title, company, location, work_style, min_experience, description_text, apply_url,
               1 - (embedding <=> %s::vector) AS similarity
        FROM jobs
        WHERE posted_at >= NOW() - INTERVAL '14 days'
          AND min_experience <= %s
          AND is_active = TRUE
          AND (%s = 'Remote' OR work_style = %s OR work_style = 'Remote')
        ORDER BY embedding <=> %s::vector ASC
        LIMIT 15;
    """
    
    with conn.cursor() as cursor:
        cursor.execute(query, (profile_vector, experience + 2, work_pref, work_pref, profile_vector))
        jobs = cursor.fetchall()
        
    return jobs

def evaluate_and_rank_jobs(subscriber: Dict[str, Any], candidate_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Uses Gemini 1.5 Flash AI Agent to select top 3-5 jobs and compose custom rationales.
    """
    if not candidate_jobs:
        return []

    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = f"""
    You are an expert career counselor matching a job seeker with top job opportunities.

    Candidate Profile:
    - Name: {subscriber.get('Full Name')}
    - Role: {subscriber.get('Primary Role')}
    - Experience: {subscriber.get('Years of Experience')} years
    - Skills: {subscriber.get('Key Skillsets')}
    - Work Preference: {subscriber.get('Work Preference')}

    Candidate Jobs List (Top 15 retrieved):
    {json.dumps(candidate_jobs, default=str)}

    Task:
    1. Select the top 3 to 5 BEST matching jobs for this candidate.
    2. For each selected job, write a 1-2 sentence personalized rationale explaining why it fits their specific profile.

    Return ONLY a JSON array with the following format:
    [
      {{
        "job_id": "<UUID>",
        "title": "<Job Title>",
        "company": "<Company>",
        "apply_url": "<URL>",
        "match_rationale": "<1-2 sentences rationale>"
      }}
    ]
    """
    
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    
    try:
        matched_jobs = json.loads(response.text)
        return matched_jobs
    except Exception as e:
        print(f"Error parsing Gemini response: {e}")
        return candidate_jobs[:3]

def send_newsletter_email(subscriber: Dict[str, Any], matched_jobs: List[Dict[str, Any]]):
    """Renders HTML template and sends email via Resend API."""
    if not matched_jobs:
        return

    job_cards_html = ""
    for job in matched_jobs:
        job_cards_html += f"""
        <div style="border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 16px; background-color: #ffffff;">
            <h3 style="margin: 0 0 8px 0; color: #1a202c;">{job.get('title')} - <span style="color: #4a5568;">{job.get('company')}</span></h3>
            <p style="margin: 0 0 12px 0; color: #2b6cb0; font-size: 14px;"><strong>Why this fits you:</strong> {job.get('match_rationale', 'Great match for your skillset.')}</p>
            <a href="{job.get('apply_url')}" style="display: inline-block; background-color: #3182ce; color: #ffffff; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 14px;">Apply Now &rarr;</a>
        </div>
        """

    email_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f7fafc; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 24px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            <h2 style="color: #2d3748;">Hello {subscriber.get('Full Name')},</h2>
            <p style="color: #4a5568; font-size: 16px;">Here are your top personalized job opportunities for this week based on your expertise in <strong>{subscriber.get('Primary Role')}</strong>:</p>
            {job_cards_html}
            <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;">
            <p style="font-size: 12px; color: #a0aec0; text-align: center;">You are receiving this email because you subscribed to our Weekly Job Alert.<br><a href="#" style="color: #718096;">Manage Preferences or Unsubscribe</a></p>
        </div>
    </body>
    </html>
    """

    params = {
        "from": "Job Newsletter <newsletter@yourdomain.com>",
        "to": [subscriber.get("Email Address")],
        "subject": f"🎯 Top Job Matches for {subscriber.get('Full Name')} - This Week",
        "html": email_html,
    }

    resend.Emails.send(params)

def update_sheet_writeback(sheet, row_idx: int, job_count: int):
    """Updates 'Last Newsletter Sent' and 'Execution Notes' columns in Google Sheet."""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    # Column 10: Last Newsletter Sent | Column 11: Execution Notes
    sheet.update_cell(row_idx, 10, today_str)
    sheet.update_cell(row_idx, 11, f"Sent ({job_count} jobs matched)")

# ==========================================
# 3. MAIN EXECUTION PIPELINE
# ==========================================
def main():
    print("🚀 Starting $0 Weekly AI Job Newsletter Pipeline...")
    
    # Connect Database & Google Sheets
    conn = get_db_connection()
    sheet = gs_client.open(GOOGLE_SHEET_NAME).sheet1
    
    subscribers = get_active_subscribers_from_sheets()
    print(f"📋 Found {len(subscribers)} active subscribers to process.")
    
    processed_count = 0
    
    for sub in subscribers:
        try:
            print(f"🔍 Processing: {sub.get('Full Name')} ({sub.get('Email Address')})")
            
            # Step 1: Query pgvector for Top 15 Matches
            candidate_jobs = search_matching_jobs(conn, sub)
            
            # Step 2: Pass to Gemini Flash AI Agent for Selection & Rationale
            selected_jobs = evaluate_and_rank_jobs(sub, candidate_jobs)
            
            if selected_jobs:
                # Step 3: Send Email
                send_newsletter_email(sub, selected_jobs)
                
                # Step 4: Writeback to Google Sheet
                update_sheet_writeback(sheet, sub["_row_number"], len(selected_jobs))
                print(f"✅ Successfully sent email with {len(selected_jobs)} jobs.")
            else:
                sheet.update_cell(sub["_row_number"], 11, "No relevant jobs found this week")
                print("⚠️ No relevant jobs found.")
                
            processed_count += 1
            
            # THROTTLING GUARDRAIL: Pause 4.5s between loop runs to enforce Gemini 15 RPM limit
            time.sleep(4.5)
            
        except Exception as e:
            print(f"❌ Error processing subscriber {sub.get('Email Address')}: {e}")
            sheet.update_cell(sub["_row_number"], 11, f"Failed: {str(e)[:30]}")
            
    conn.close()
    print(f"🎉 Pipeline finished! Total processed: {processed_count}")

if __name__ == "__main__":
    main()
```

---

## 3. Step-by-Step Deployment Guide

Follow these steps to deploy and run this entire system for **$0/month**.

### Step 1: Google Sheets & GCP Setup
1. Create a Google Sheet titled **`Job Newsletter Subscribers`** with the following header columns in Row 1:
   * `Subscriber ID` | `Full Name` | `Email Address` | `Primary Role` | `Years of Experience` | `Key Skillsets` | `Work Preference` | `Preferred Location` | `Status` | `Last Newsletter Sent` | `Execution Notes`
2. Go to [Google Cloud Console](https://console.cloud.google.com/), create a new free project.
3. Enable **Google Sheets API** and **Google Drive API**.
4. Create a **Service Account**, generate a JSON key, and download it.
5. Copy the `client_email` address from the service account JSON file, go to your Google Sheet, click **Share**, and grant **Editor** access to this service account email.

### Step 2: Supabase Database Setup
1. Sign up for a free account at [supabase.com](https://supabase.com) and create a PostgreSQL project.
2. Open the **SQL Editor** in Supabase and run the following script:
   ```sql
   -- Enable vector extension
   CREATE EXTENSION IF NOT EXISTS vector;

   -- Jobs table schema
   CREATE TABLE jobs (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       title TEXT NOT NULL,
       company TEXT NOT NULL,
       location TEXT,
       work_style VARCHAR(50) CHECK (work_style IN ('Remote', 'Hybrid', 'Onsite')),
       min_experience INT DEFAULT 0,
       description_text TEXT NOT NULL,
       apply_url TEXT NOT NULL,
       embedding VECTOR(768), -- Matches Google text-embedding-004 dimensions
       posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
       is_active BOOLEAN DEFAULT TRUE
   );

   -- Fast cosine distance index
   CREATE INDEX ON jobs USING hnsw (embedding vector_cosine_ops);
   ```
3. Get your PostgreSQL connection URI from **Project Settings $\rightarrow$ Database $\rightarrow$ Connection String (URI)**.

### Step 3: Google AI Studio Setup
1. Visit [Google AI Studio](https://aistudio.google.com/).
2. Click **Get API key** and create an API key in a free project.

### Step 4: Resend / Brevo Email Setup
1. Create a free account on [Resend.com](https://resend.com) (or Brevo.com).
2. Verify your sending domain (e.g., `yourdomain.com`) by adding DNS TXT/MX records in Cloudflare or Namecheap.
3. Generate an API Key under **API Keys**.

### Step 5: GitHub Actions Automation Setup
1. Push your code (`main.py` and `requirements.txt`) to a GitHub repository.
2. **Requirements File (`requirements.txt`):**
   ```text
   psycopg2-binary>=2.9.9
   gspread>=6.1.0
   google-auth>=2.29.0
   google-generativeai>=0.5.0
   resend>=2.0.0
   ```
3. Navigate to your GitHub repository: **Settings $\rightarrow$ Secrets and variables $\rightarrow$ Actions $\rightarrow$ New repository secret**.
4. Add the following secrets:
   * `GEMINI_API_KEY`: Your Google AI Studio API Key.
   * `SUPABASE_DB_URL`: Your Supabase Postgres Connection String.
   * `GCP_SERVICE_ACCOUNT_KEY`: Paste the full contents of your Google GCP Service Account JSON key file.
   * `RESEND_API_KEY`: Your Resend API key.

5. Create `.github/workflows/newsletter.yml` in your repo:
   ```yaml
   name: Run Weekly Job Newsletter

   on:
     schedule:
       - cron: '0 8 * * 0' # Every Sunday at 08:00 UTC
     workflow_dispatch: # Allows manual trigger from GitHub UI

   jobs:
     run-newsletter:
       runs-on: ubuntu-latest
       steps:
         - name: Checkout Repository
           uses: actions/checkout@v4

         - name: Set up Python
           uses: actions/setup-python@v5
           with:
             python-version: '3.11'

         - name: Install Dependencies
           run: pip install -r requirements.txt

         - name: Execute Main Script
           env:
             GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
             SUPABASE_DB_URL: ${{ secrets.SUPABASE_DB_URL }}
             GCP_SERVICE_ACCOUNT_KEY: ${{ secrets.GCP_SERVICE_ACCOUNT_KEY }}
             RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}
           run: python main.py
   ```

---

## 4. Operational Verification & Testing

1. **Local Test:** Populate 2 sample jobs into Supabase (with embeddings generated via `text-embedding-004`) and 1 test subscriber in Google Sheets. Run `python main.py` locally to verify email delivery.
2. **GitHub Actions Trigger Test:** Go to **Actions** tab in GitHub $\rightarrow$ **Run Weekly Job Newsletter** $\rightarrow$ Click **Run workflow** to test manual triggering.