"""Ingest REAL verified jobs (Oct 2026, India) with Gemini embeddings."""
from db import get_db_connection
from embeddings import generate_embedding

JOBS = [
    # --- test (Python 9y, Bangalore) ---
    {"title": "Senior Data Scientist (Data & Analytics) - Python", "company": "Amgen", "location": "Hyderabad, India",
     "work_style": "Onsite", "min_experience": 7, "max_experience": 11,
     "required_skills": ["Python", "SQL", "Machine Learning", "Tableau", "Data Science"],
     "description_text": "Apply data science and analytics to biotech problems. Python/R/SQL, dashboards Tableau/PowerBI, deploy ML models. Masters or Bachelors + 7-11 years.",
     "apply_url": "https://careers.amgen.com/en/job/hyderabad/senior-data-scientist-data-and-analytics-python/87/99394951456"},
    {"title": "Senior Data Scientist", "company": "DAZN", "location": "Hyderabad, India",
     "work_style": "Onsite", "min_experience": 5, "max_experience": 10,
     "required_skills": ["Python", "Machine Learning", "Data Science", "SQL", "Analytics"],
     "description_text": "Sports streaming data science in Hyderabad tech hub. Build models on fan and content data. Permanent full-time onsite.",
     "apply_url": "https://careers.dazn.com/postings/e176c5b3-8f32-4b04-89d2-3f825720da2c"},
    {"title": "EY GDS Consulting AI & Data - Forward Deployed Engineer Manager", "company": "EY", "location": "Bengaluru, India",
     "work_style": "Hybrid", "min_experience": 9, "max_experience": 15,
     "required_skills": ["Python", "GenAI", "LLM", "RAG", "Data Science"],
     "description_text": "Lead GenAI deployments with clients. 9+ years hands-on, LLM apps, RAG systems, agentic workflows. Elite IC role in Bengaluru.",
     "apply_url": "https://in.linkedin.com/jobs/view/ey-gds-consulting-ai-and-data-forward-deployed-engineer-manager-at-ey-4425795630"},
    # --- karuna tk5013 (Presales 16y, Chennai) ---
    {"title": "Solution Consultant - Presales", "company": "Chargebee", "location": "Chennai, India",
     "work_style": "Hybrid", "min_experience": 5, "max_experience": 10,
     "required_skills": ["Presales", "SaaS", "Solution Consulting", "APIs", "Consulting"],
     "description_text": "Own solution design for subscription billing platform. Work with sales on demos, discovery, ROI narratives. 3+ years SaaS/consulting, Chennai.",
     "apply_url": "https://getmereferred.com/in/job-listing/solution-consultant-presales-chargebee-intnchennai-5-to-10-years-experience-a55c5f0b-7735-4d34-83f1-f9853ecb281b"},
    {"title": "Pre-Sales Solutions Consultant", "company": "WATI.io", "location": "Remote India",
     "work_style": "Remote", "min_experience": 3, "max_experience": 8,
     "required_skills": ["Presales", "SaaS", "WhatsApp API", "Consulting", "Demos"],
     "description_text": "WhatsApp business platform presales. Demos, discovery, solution mapping for SMB/enterprise. Remote India.",
     "apply_url": "https://apply.workable.com/j/D60B1FAA10"},
    {"title": "Solutions Consultant (Pre-Sales) Enterprise SaaS Demos", "company": "Jolly Technologies", "location": "Chennai, India",
     "work_style": "Remote", "min_experience": 3, "max_experience": 12,
     "required_skills": ["Presales", "SaaS", "Demos", "APIs", "Consulting"],
     "description_text": "Live enterprise SaaS demos worldwide, remote contract. 3+ years presales, SSO/APIs/security. Rs 22-32L. Chennai, US-shift remote.",
     "apply_url": "https://www.jollytech.com/company/jobs/positions/jol-sle-in-101326.php"},
    # --- Ayyappa (Java/Selenium 13y, Hyderabad) ---
    {"title": "Automation Test Engineer - Selenium Java API Testing", "company": "Synechron", "location": "Hyderabad, India",
     "work_style": "Hybrid", "min_experience": 5, "max_experience": 10,
     "required_skills": ["Java", "Selenium", "API Testing", "Rest Assured", "Automation"],
     "description_text": "Banking-tech automation: Selenium Java + API testing with Rest Assured. Hyderabad hybrid. JR1043750.",
     "apply_url": "https://synechron.wd1.myworkdayjobs.com/en-US/SynechronCareers/job/Automation-Test-Engineer---Selenium--Java---API-Testing_JR1043750"},
]

if __name__ == "__main__":
    conn = get_db_connection()
    n = 0
    with conn.cursor() as cur:
        for j in JOBS:
            text = f"{j['title']} at {j['company']}. {j['description_text']} Skills: {', '.join(j['required_skills'])}"
            emb = generate_embedding(text)
            cur.execute(
                """INSERT INTO jobs (title, company, location, work_style, min_experience,
                   max_experience, required_skills, description_text, apply_url, embedding)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)""",
                (j["title"], j["company"], j["location"], j["work_style"], j["min_experience"],
                 j["max_experience"], j["required_skills"], j["description_text"], j["apply_url"], emb))
            n += 1
    conn.commit()
    conn.close()
    print(f"Ingested {n} REAL jobs.")
