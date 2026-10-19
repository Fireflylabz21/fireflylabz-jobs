"""Seed sample jobs into Supabase (generates real Gemini embeddings).
Usage: python seed_jobs.py
Requires: GEMINI_API_KEY + SUPABASE_DB_URL in .env
"""
from db import get_db_connection
from embeddings import generate_embedding

SAMPLES = [
    {"title": "Senior Frontend Engineer", "company": "Acme Labs", "location": "Remote",
     "work_style": "Remote", "min_experience": 4, "max_experience": 8,
     "required_skills": ["React", "TypeScript", "Next.js"],
     "description_text": "Build React/TypeScript marketing app with Next.js and Tailwind. 5+ years frontend.",
     "apply_url": "https://example.com/jobs/fe1"},
    {"title": "Backend Engineer (Python)", "company": "Datawise", "location": "Chicago, IL",
     "work_style": "Hybrid", "min_experience": 2, "max_experience": 5,
     "required_skills": ["Python", "PostgreSQL", "AWS"],
     "description_text": "Python APIs, Postgres, AWS. 2-5 years backend experience.",
     "apply_url": "https://example.com/jobs/be1"},
    {"title": "Junior Frontend Developer", "company": "Startup XYZ", "location": "Remote",
     "work_style": "Remote", "min_experience": 0, "max_experience": 2,
     "required_skills": ["JavaScript", "React", "CSS"],
     "description_text": "Entry-level React work, mentorship provided. Great for 0-2 years.",
     "apply_url": "https://example.com/jobs/jr1"},
]

if __name__ == "__main__":
    conn = get_db_connection()
    with conn.cursor() as cur:
        for j in SAMPLES:
            text = f"{j['title']} at {j['company']}. {j['description_text']} Skills: {', '.join(j['required_skills'])}"
            emb = generate_embedding(text)
            cur.execute(
                """INSERT INTO jobs (title, company, location, work_style, min_experience,
                   max_experience, required_skills, description_text, apply_url, embedding)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)""",
                (j["title"], j["company"], j["location"], j["work_style"], j["min_experience"],
                 j["max_experience"], j["required_skills"], j["description_text"], j["apply_url"], emb))
    conn.commit()
    conn.close()
    print(f"Seeded {len(SAMPLES)} jobs.")
