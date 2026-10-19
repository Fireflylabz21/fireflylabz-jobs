"""Multi-tier matching engine.
Tier 1: deterministic SQL filters (recency, experience, location) - FR-3.1
Tier 2: pgvector cosine similarity, top 15 - FR-3.2
"""
from typing import Any, Dict, List
from config import JOB_LOOKBACK_DAYS
from embeddings import generate_embedding, profile_text_for


def search_matching_jobs(conn, subscriber: Dict[str, Any], limit: int = 15) -> List[Dict[str, Any]]:
    profile_text = profile_text_for(subscriber)
    profile_vector = generate_embedding(profile_text)

    experience = int(subscriber.get("_experience_years", 0) or 0)
    work_pref = subscriber.get("_work_pref", "Flexible") or "Flexible"
    pref_city = (subscriber.get("_location", "") or "").strip().lower()

    # FR-3.1: fresh jobs, candidate exp within [minExp, maxExp+2].
    # Work-style: Flexible/Any sees all (ranked by vector+location below).
    # Remote-only sees Remote only. Hybrid/Onsite sees matching city + Remote.
    if work_pref in ("Flexible", "Any", ""):
        ws_clause = "AND (work_style IN ('Remote','Hybrid','Onsite') OR work_style IS NULL)"
        ws_params: tuple = ()
    elif work_pref == "Remote":
        ws_clause = "AND (work_style = 'Remote' OR work_style IS NULL)"
        ws_params = ()
    else:  # Hybrid / Onsite: city + Remote fallback
        ws_clause = "AND (work_style = %s OR work_style = 'Remote' OR work_style IS NULL)"
        ws_params = (work_pref,)
    query = f"""
        SELECT id, title, company, location, work_style,
               min_experience, max_experience, required_skills,
               description_text, apply_url,
               1 - (embedding <=> %s::vector) AS similarity
        FROM jobs
        WHERE posted_at >= NOW() - (%s || ' days')::INTERVAL
          AND min_experience <= %s
          AND (is_active IS NULL OR is_active = TRUE)
          AND embedding IS NOT NULL
          {ws_clause}
        ORDER BY embedding <=> %s::vector ASC
        LIMIT %s;
    """
    with conn.cursor() as cur:
        cur.execute(query, (profile_vector, str(JOB_LOOKBACK_DAYS), experience + 2,
                            *ws_params, profile_vector, limit))
        rows = cur.fetchall()

    jobs = [dict(r) for r in rows]

    # Python-side: exact-city first (Bangalore->Bengaluru), then Remote, then other cities.
    # Within each tier, higher vector similarity wins.
    if pref_city:
        alias = {"bangalore": "bengaluru", "bengaluru": "bangalore"}
        alt = alias.get(pref_city, "")

        def _tier(j: Dict[str, Any]) -> int:
            loc = (j.get("location", "") or "").lower()
            ws = (j.get("work_style", "") or "")
            if pref_city in loc or (alt and alt in loc):
                return 2
            if ws == "Remote":
                return 1
            return 0

        def _score(j: Dict[str, Any]) -> tuple:
            return (_tier(j), float(j.get("similarity", 0) or 0))

        jobs.sort(key=_score, reverse=True)
    return jobs
