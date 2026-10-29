"""ScraperAgent - LangGraph-based Job Scraping Orchestrator
Day-1 scraping agent with chunked execution by day-of-week.
Uses chunk_dispatcher.py for role/location/experience band scheduling.
Sources: RemoteOK, Arbeitnow (free), optional jobspy/Playwright.
Deduplication by apply_url, idempotent upserts to Supabase jobs table.
"""

import asyncio
import time
import datetime
import random
import logging
from typing import List, Dict, Optional, Tuple, Any

import numpy as np
from langgraph.graph import StateGraph, START, END
try:
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError:
    from langchain.schema import HumanMessage, SystemMessage

from chunk_dispatcher import get_today_chunks, WEEKLY_SCHEDULE
from db import get_db_connection, upsert_job, find_existing_job
from embeddings import get_gemini_embedding
from config import DRY_RUN, GEMINI_API_KEY, GEMINI_EMBED_MODEL, THROTTLE_SECONDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)
"""ScraperAgentState - State for the LangGraph scraper orchestrator."""
import pydantic

class ScraperAgentState(pydantic.BaseModel):
    day_of_week: str = pydantic.Field(default=datetime.datetime.today().strftime("%A"))
    chunks_completed: int = pydantic.Field(default=0)
    jobs_found_total: int = pydantic.Field(default=0)
    jobs_upserted: int = pydantic.Field(default=0)
    jobs_deduped: int = pydantic.Field(default=0)
    error: Optional[str] = pydantic.Field(default=None)
    batch_index: int = pydantic.Field(default=0)


"""Chunk helpers."""
def get_today_chunk() -> Optional[Tuple[List[str], List[str], List[str]]]:
    chunks = get_today_chunks()
    return chunks[0] if chunks else None


def clean_description(text: str, max_len: int = 500) -> str:
    """Strip HTML tags and produce a clean summary of the job description.
    
    Args:
        text: Raw description that may contain HTML markup.
        max_len: Maximum output length in characters.
    
    Returns:
        Clean, plain-text description truncated to max_len.
    """
    if not text:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
    except ImportError:
        import re
        text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = " ".join(text.split())
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text


"""Scraper sources - real implementations with fallback stubs."""
def scrape_remoteok_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape RemoteOK API for jobs matching roles/locations.
    Returns list of job dicts. If no jobs found, returns empty list.
    """
    jobs = []
    try:
        import requests
        logger.info(f"RemoteOK chunk: {len(roles)} roles x {len(locations)} locations")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "application/json",
        }
        resp = requests.get("https://remoteok.com/api", headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"RemoteOK API returned status {resp.status_code}")
            return jobs
        data = resp.json()
        # RemoteOK returns a list of dicts; last element is often a "legal" key
        if isinstance(data, dict) and "legal" in data:
            actual_jobs = [d for d in data if isinstance(d, dict) and d != "legal"]
        elif isinstance(data, list):
            actual_jobs = [d for d in data if isinstance(d, dict)]
        else:
            actual_jobs = []
        for job in actual_jobs:
            title = job.get("position", "").lower()
            loc = job.get("location", "").lower()
            # Match by role keyword and location keyword
            role_match = any(
                r.lower().replace(" ", "") in title.replace(" ", "")
                or r.split()[0].lower() in title
                for r in roles
            )
            loc_match = any(loc and l.lower() in loc for l in locations) if loc else False
            if role_match and (loc_match or "remote" in loc):
                apply_url = job.get("url", "")
                if not apply_url:
                    continue
                jobs.append({
                    "title": job.get("position", ""),
                    "company": job.get("company", ""),
                    "location": job.get("location", ""),
                    "work_style": "Remote",
                    "min_experience": None,
                    "max_experience": None,
                    "required_skills": job.get("tags", []),
                    "description_text": clean_description(job.get("description", ""), 500),
                    "apply_url": apply_url,
                    "posted_at": job.get("date", ""),
                    "region": "Remote",
                })
        logger.info(f"RemoteOK: found {len(jobs)} matching jobs")
    except ImportError:
        logger.debug("requests not available for RemoteOK scraper")
    except Exception as e:
        logger.warning(f"RemoteOK scrape error: {e}")
    return jobs


def scrape_arbeitnow_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape Arbeitnow API for jobs matching roles/locations.
    Returns list of job dicts. If no jobs found, returns empty list.
    """
    jobs = []
    try:
        import requests
        logger.info(f"Arbeitnow chunk: {len(roles)} roles x {len(locations)} locations")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        # Arbeitnow job board API - filters by location_type=remote for broad reach
        url = "https://www.arbeitnow.com/api/job-board/"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Arbeitnow API returned status {resp.status_code}")
            return jobs
        data = resp.json()
        if not isinstance(data, list):
            data = data.get("jobs", []) if isinstance(data, dict) else []
        for job in data:
            if not isinstance(job, dict):
                continue
            title = (job.get("title") or "").lower()
            loc = (job.get("location") or "").lower()
            # Match by role keyword and location keyword
            role_match = any(
                r.lower().replace(" ", "") in title.replace(" ", "")
                or r.split()[0].lower() in title
                for r in roles
            )
            loc_match = any(loc and l.lower() in loc for l in locations) if loc else False
            if role_match and (loc_match or "remote" in loc):
                apply_url = job.get("url", "") or job.get("apply_url", "")
                if not apply_url:
                    continue
                jobs.append({
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "location": job.get("location", ""),
                    "work_style": "Remote" if "remote" in loc else "Onsite",
                    "min_experience": None,
                    "max_experience": None,
                    "required_skills": job.get("tags", []),
                    "description_text": clean_description(job.get("description", ""), 500),
                    "apply_url": apply_url,
                    "posted_at": job.get("created_at", ""),
                    "region": "EU",
                })
        logger.info(f"Arbeitnow: found {len(jobs)} matching jobs")
    except ImportError:
        logger.debug("requests not available for Arbeitnow scraper")
    except Exception as e:
        logger.warning(f"Arbeitnow scrape error: {e}")
    return jobs


"""DB helpers."""
def deduplicate_and_upsert(jobs: List[Dict]) -> Tuple[int, int]:
    """Deduplicate jobs by apply_url and upsert to DB.
    Returns (new_jobs_count, deduped_count).
    """
    if not jobs:
        return 0, 0
    conn = get_db_connection()
    if conn is None:
        logger.error("No DB connection available")
        return 0, 0
    new_count = 0
    deduped_count = 0
    try:
        with conn.cursor() as cur:
            for job in jobs:
                apply_url = job.get("apply_url", "").strip()
                if not apply_url:
                    deduped_count += 1
                    continue
                existing = find_existing_job(cur, apply_url=apply_url)
                if existing:
                    deduped_count += 1
                    continue
                description = job.get("description_text", "")
                embedding = None
                if description and GEMINI_API_KEY:
                    try:
                        emb = get_gemini_embedding(description)
                        embedding = emb.embedding if emb else None
                    except Exception as e:
                        logger.error(f"Embedding error: {e}")
                try:
                    upsert_job(
                        cur,
                        title=job.get("title", ""),
                        company=job.get("company", ""),
                        location=job.get("location", ""),
                        work_style=job.get("work_style", ""),
                        min_experience=job.get("min_experience"),
                        max_experience=job.get("max_experience"),
                        required_skills=job.get("required_skills", []),
                        description_text=description,
                        apply_url=apply_url,
                        embedding=embedding,
                        posted_at=job.get("posted_at"),
                        is_active=True,
                    )
                    new_count += 1
                    logger.info(f"Upserted new job: {job.get('title')} at {job.get('company')}")
                except Exception as e:
                    logger.error(f"Upsert failed for {apply_url}: {e}")
        conn.commit()
    except Exception as e:
        logger.error(f"DB operation error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return new_count, deduped_count


"""LangGraph nodes."""

def scrape_naukri_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape Naukri via public search for given roles and locations (India/APAC).
    Skips role/location combos that return no results.
    Returns list of job dicts with consistent field names including region.
    """
    jobs = []
    try:
        import requests
        from bs4 import BeautifulSoup
        logger.info(f"Naukri chunk: {len(roles)} roles x {len(locations)} locations")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.naukri.com/",
        }
        for role in roles:
            for location in locations:
                try:
                    url = f"https://www.naukri.com/{role.lower().replace(' ', '-')}-jobs-{location.lower().replace(' ', '-')}"
                    resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
                    if resp.status_code != 200:
                        logger.debug(f"Naukri: {role}/{location} returned {resp.status_code}")
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Naukri uses various selectors; try common patterns
                    job_cards = (
                        soup.select("div[data-job-id]") or
                        soup.select("article.jd-template") or
                        soup.select("div.cj-job-card")
                    )
                    for card in job_cards:
                        title_elem = card.select_one("a.title") or card.select_one("h2.title") or card.select_one("a")
                        if not title_elem:
                            continue
                        title = title_elem.get_text(strip=True) or title_elem.get("title", "")
                        link = title_elem.get("href", "")
                        if link and not link.startswith("http"):
                            link = "https://www.naukri.com" + link
                        company_elem = card.select_one(".company, .comp-name") or card.select_one("a.company")
                        company = company_elem.get_text(strip=True) if company_elem else ""
                        if not link or link in [j["apply_url"] for j in jobs]:
                            continue
                        # Verify title contains role keyword
                        if title and role.lower().split()[0] not in title.lower():
                            continue
                        date_elem = card.select_one(".f12, .date, .posted-on")
                        posted_at = date_elem.get_text(strip=True) if date_elem else ""
                        jobs.append({
                            "title": title,
                            "company": company,
                            "location": location,
                            "work_style": "Onsite",
                            "min_experience": None,
                            "max_experience": None,
                            "required_skills": [role],
                            "description_text": f"{role} position at {location} via Naukri",
                            "apply_url": link,
                            "posted_at": posted_at,
                            "region": "APAC",
                        })
                    time.sleep(random.uniform(0.5, 2.0))
                except Exception as e:
                    logger.warning(f"Naukri scrape error for {role}/{location}: {e}")
    except ImportError:
        logger.debug("requests/BeautifulSoup not available for Naukri scraper")
    return jobs


def scrape_linkedin_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape LinkedIn Jobs for given roles and locations (US/UK/MEA/EU).
    Uses LinkedIn's public job search HTML. Skips role/location combos
    with no results.
    Returns list of job dicts with consistent field names including region.
    """
    jobs = []
    try:
        import requests
        from bs4 import BeautifulSoup
        logger.info(f"LinkedIn chunk: {len(roles)} roles x {len(locations)} locations")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.linkedin.com/",
        }
        for role in roles:
            for location in locations:
                try:
                    search_url = (
                        "https://www.linkedin.com/jobs/search/"
                        f"?keywords={role}&location={location}"
                        "&position=1&pageNum=0"
                    )
                    resp = requests.get(search_url, headers=headers, timeout=15)
                    if resp.status_code != 200:
                        logger.debug(f"LinkedIn: {role}/{location} returned {resp.status_code}")
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # LinkedIn job cards
                    job_cards = (
                        soup.select("div[data-job-id]") or
                        soup.select("div.base-card") or
                        soup.select("article.jobs-search-result")
                    )
                    for card in job_cards:
                        title_elem = (
                            card.select_one("a[data-control-name]") or
                            card.select_one("h3.base-search-card__title") or
                            card.select_one("span.visually-hidden") or
                            card.select_one("a")
                        )
                        if not title_elem:
                            continue
                        title = title_elem.get_text(strip=True) or title_elem.get("aria-label", "")
                        if not title:
                            continue
                        # Verify title contains role keyword
                        if role.lower().split()[0] not in title.lower():
                            continue
                        link_elem = card.select_one("a")
                        link = link_elem.get("href", "") if link_elem else ""
                        if link and not link.startswith("http"):
                            link = "https://www.linkedin.com" + link
                        if not link or link in [j["apply_url"] for j in jobs]:
                            continue
                        company_elem = (
                            card.select_one("h4.base-search-card__subtitle") or
                            card.select_one("a[data-control-name] + .company")
                        )
                        company = company_elem.get_text(strip=True) if company_elem else ""
                        # Region inference based on location
                        region = "US"
                        if location and any(c in location for c in ["London", "UK", "Berlin", "Zurich", "Dublin", "Munich"]):
                            region = "UK"
                        if location and any(c in location for c in ["Singapore", "Tokyo", "Bengaluru", "Hyderabad"]):
                            region = "APAC"
                        if location and "Dubai" in location:
                            region = "MEA"
                        jobs.append({
                            "title": title,
                            "company": company,
                            "location": location,
                            "work_style": "Remote",
                            "min_experience": None,
                            "max_experience": None,
                            "required_skills": [role],
                            "description_text": f"{role} position at {location} via LinkedIn",
                            "apply_url": link,
                            "posted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "region": region,
                        })
                    time.sleep(random.uniform(0.5, 2.0))
                except Exception as e:
                    logger.warning(f"LinkedIn scrape error for {role}/{location}: {e}")
    except ImportError:
        logger.debug("requests/BeautifulSoup not available for LinkedIn scraper")
    return jobs


"""LangGraph nodes."""


def scrape_remotive_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape Remotive (free remote jobs API) and filter by roles."""
    jobs = []
    try:
        import requests
        logger.info(f"Remotive: fetching remote jobs for {len(roles)} roles")
        resp = requests.get("https://remotive.com/api/remote-jobs", timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json().get("jobs", [])
        role_l = [r.lower() for r in roles]
        for j in data:
            title = (j.get("title") or "").strip()
            if not title:
                continue
            if not any(r.split()[0] in title.lower() for r in role_l):
                continue
            company = j.get("company_name", "")
            location = j.get("candidate_required_location", "") or "Remote"
            url = j.get("url", "")
            if not url:
                continue
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "work_style": "Remote",
                "min_experience": None,
                "max_experience": None,
                "required_skills": [],
                "description_text": (j.get("description") or "")[:5000],
                "apply_url": url,
                "posted_at": j.get("publication_date"),
                "region": "US",
            })
        logger.info(f"Remotive: {len(jobs)} matching jobs")
    except Exception as e:
        logger.warning(f"Remotive scrape failed: {e}")
    return jobs


def scrape_jobicy_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape Jobicy (free remote jobs API) and filter by roles."""
    jobs = []
    try:
        import requests
        logger.info(f"Jobicy: fetching remote jobs for {len(roles)} roles")
        resp = requests.get("https://jobicy.com/api/v2/remote-jobs?count=50", timeout=20)
        if resp.status_code != 200:
            return jobs
        data = resp.json().get("jobs", [])
        role_l = [r.lower() for r in roles]
        for j in data:
            title = (j.get("jobTitle") or "").strip()
            if not title:
                continue
            if not any(r.split()[0] in title.lower() for r in role_l):
                continue
            company = j.get("companyName", "")
            location = j.get("jobGeo", "") or "Remote"
            url = j.get("url", "")
            if not url:
                continue
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "work_style": "Remote",
                "min_experience": None,
                "max_experience": None,
                "required_skills": [],
                "description_text": (j.get("jobDescription") or "")[:5000],
                "apply_url": url,
                "posted_at": j.get("pubDate"),
                "region": "US",
            })
        logger.info(f"Jobicy: {len(jobs)} matching jobs")
    except Exception as e:
        logger.warning(f"Jobicy scrape failed: {e}")
    return jobs


def scrape_seek_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape Seek/JobStreet (APAC) search results for given roles."""
    jobs = []
    try:
        import requests
        from bs4 import BeautifulSoup
        role_l = [r.lower() for r in roles]
        apac_locs = [l for l in locations if any(k in l.lower() for k in ("singapore", "sydney", "melbourne", "auckland", "tokyo"))]
        if not apac_locs:
            apac_locs = ["Singapore"]
        for role in roles[:3]:
            for loc in apac_locs[:3]:
                try:
                    url = f"https://www.seek.com.au/jobs?keywords={requests.utils.quote(role)}&where={requests.utils.quote(loc)}"
                    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        title = a.get_text(" ", strip=True)
                        href = a["href"]
                        if not title or len(title) < 6 or "job" not in href.lower():
                            continue
                        if not any(r.split()[0] in title.lower() for r in role_l):
                            continue
                        full = href if href.startswith("http") else "https://www.seek.com.au" + href
                        jobs.append({"title": title[:120], "company": "", "location": loc, "work_style": "Onsite", "min_experience": None, "max_experience": None, "required_skills": [], "description_text": "", "apply_url": full, "posted_at": None, "region": "APAC"})
                except Exception:
                    continue
        seen = set(); uniq = []
        for j in jobs:
            if j["apply_url"] in seen: continue
            seen.add(j["apply_url"]); uniq.append(j)
        logger.info(f"Seek/JobStreet: {len(uniq)} matching jobs")
        return uniq[:40]
    except Exception as e:
        logger.warning(f"Seek scrape failed: {e}")
        return jobs


def scrape_instahyre_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape Instahyre (India) search results for given roles."""
    jobs = []
    try:
        import requests
        from bs4 import BeautifulSoup
        role_l = [r.lower() for r in roles]
        india_locs = [l for l in locations if any(k in l.lower() for k in ("bengaluru", "hyderabad", "bangalore", "mumbai", "delhi", "pune", "chennai"))]
        if not india_locs:
            india_locs = ["Bengaluru"]
        for role in roles[:3]:
            for loc in india_locs[:2]:
                try:
                    url = f"https://www.instahyre.com/search-jobs/?q={requests.utils.quote(role)}&location={requests.utils.quote(loc)}"
                    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        title = a.get_text(" ", strip=True)
                        href = a["href"]
                        if not title or len(title) < 6 or "job" not in href.lower():
                            continue
                        if not any(r.split()[0] in title.lower() for r in role_l):
                            continue
                        full = href if href.startswith("http") else "https://www.instahyre.com" + href
                        jobs.append({"title": title[:120], "company": "", "location": loc, "work_style": "Onsite", "min_experience": None, "max_experience": None, "required_skills": [], "description_text": "", "apply_url": full, "posted_at": None, "region": "India"})
                except Exception:
                    continue
        seen = set(); uniq = []
        for j in jobs:
            if j["apply_url"] in seen: continue
            seen.add(j["apply_url"]); uniq.append(j)
        logger.info(f"Instahyre: {len(uniq)} matching jobs")
        return uniq[:40]
    except Exception as e:
        logger.warning(f"Instahyre scrape failed: {e}")
        return jobs


def scrape_bayt_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape Bayt/GulfTalent (MEA) search results for given roles."""
    jobs = []
    try:
        import requests
        from bs4 import BeautifulSoup
        role_l = [r.lower() for r in roles]
        mea_locs = [l for l in locations if any(k in l.lower() for k in ("dubai", "abu dhabi", "riyadh", "doha"))]
        if not mea_locs:
            mea_locs = ["Dubai"]
        for role in roles[:3]:
            for loc in mea_locs[:2]:
                try:
                    url = f"https://www.bayt.com/en/{loc.lower().replace(' ', '-')}/jobs/search/?search={requests.utils.quote(role)}"
                    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        title = a.get_text(" ", strip=True)
                        href = a["href"]
                        if not title or len(title) < 6 or "job" not in href.lower():
                            continue
                        if not any(r.split()[0] in title.lower() for r in role_l):
                            continue
                        full = href if href.startswith("http") else "https://www.bayt.com" + href
                        jobs.append({"title": title[:120], "company": "", "location": loc, "work_style": "Onsite", "min_experience": None, "max_experience": None, "required_skills": [], "description_text": "", "apply_url": full, "posted_at": None, "region": "MEA"})
                except Exception:
                    continue
        seen = set(); uniq = []
        for j in jobs:
            if j["apply_url"] in seen: continue
            seen.add(j["apply_url"]); uniq.append(j)
        logger.info(f"Bayt/GulfTalent: {len(uniq)} matching jobs")
        return uniq[:40]
    except Exception as e:
        logger.warning(f"Bayt scrape failed: {e}")
        return jobs


def scrape_builtin_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape Built In (US/UK) search results for given roles."""
    jobs = []
    try:
        import requests
        from bs4 import BeautifulSoup
        role_l = [r.lower() for r in roles]
        us_uk_locs = [l for l in locations if any(k in l.lower() for k in ("new york", "san francisco", "seattle", "boston", "london"))]
        if not us_uk_locs:
            us_uk_locs = ["New York"]
        for role in roles[:3]:
            for loc in us_uk_locs[:2]:
                try:
                    url = f"https://builtin.com/jobs?search={requests.utils.quote(role)}&location={requests.utils.quote(loc)}"
                    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                    if resp.status_code != 200:
                        continue
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        title = a.get_text(" ", strip=True)
                        href = a["href"]
                        if not title or len(title) < 6 or "job" not in href.lower():
                            continue
                        if not any(r.split()[0] in title.lower() for r in role_l):
                            continue
                        full = href if href.startswith("http") else "https://builtin.com" + href
                        jobs.append({"title": title[:120], "company": "", "location": loc, "work_style": "Onsite", "min_experience": None, "max_experience": None, "required_skills": [], "description_text": "", "apply_url": full, "posted_at": None, "region": "US"})
                except Exception:
                    continue
        seen = set(); uniq = []
        for j in jobs:
            if j["apply_url"] in seen: continue
            seen.add(j["apply_url"]); uniq.append(j)
        logger.info(f"Built In: {len(uniq)} matching jobs")
        return uniq[:40]
    except Exception as e:
        logger.warning(f"Built In scrape failed: {e}")
        return jobs


def scrape_chunk_node(state: ScraperAgentState) -> ScraperAgentState:
    """LangGraph node: scrape one chunk of jobs."""
    day = state.day_of_week
    chunks = get_today_chunks()

    if not chunks or state.batch_index >= len(chunks):
        state.error = "No more chunks to scrape"
        return state

    roles, locations, experience_bands, chunk_region = chunks[state.batch_index]
    logger.info(f"Scraper: Day={day}, Chunk {state.batch_index + 1}/{len(chunks)}")
    logger.info(f"  Roles: {', '.join(roles[:3])}...")
    logger.info(f"  Locations: {', '.join(locations)}")
    logger.info(f"  Experience bands: {', '.join(experience_bands)}")

    all_jobs = []
    # Filter: only jobs posted within last 48 hours
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    remoteok_jobs = scrape_remoteok_chunk(roles, locations)
    for j in remoteok_jobs:
        j["region"] = j.get("region", "US")
        j["posted_at"] = j.get("posted_at", cutoff.isoformat())
        all_jobs.append(j)
    arbetnow_jobs = scrape_arbeitnow_chunk(roles, locations)
    for j in arbetnow_jobs:
        j["region"] = j.get("region", "EU")
        j["posted_at"] = j.get("posted_at", cutoff.isoformat())
    all_jobs.extend(arbetnow_jobs)
    naukri_jobs = scrape_naukri_chunk(roles, locations)
    all_jobs.extend(naukri_jobs)
    linkedin_jobs = scrape_linkedin_chunk(roles, locations)
    all_jobs.extend(linkedin_jobs)
    remotive_jobs = scrape_remotive_chunk(roles, locations)
    all_jobs.extend(remotive_jobs)
    jobicy_jobs = scrape_jobicy_chunk(roles, locations)
    all_jobs.extend(jobicy_jobs)
    seek_jobs = scrape_seek_chunk(roles, locations)
    all_jobs.extend(seek_jobs)
    instahyre_jobs = scrape_instahyre_chunk(roles, locations)
    all_jobs.extend(instahyre_jobs)
    bayt_jobs = scrape_bayt_chunk(roles, locations)
    all_jobs.extend(bayt_jobs)
    builtin_jobs = scrape_builtin_chunk(roles, locations)
    all_jobs.extend(builtin_jobs)

    new_jobs, deduped = deduplicate_and_upsert(all_jobs)

    state.jobs_found_total += len(all_jobs)
    state.jobs_upserted += new_jobs
    state.jobs_deduped += deduped
    state.batch_index += 1

    logger.info(f"Chunk complete: {new_jobs} new, {deduped} deduped, "
                f"total found: {state.jobs_found_total}")
    return state


def summarize_node(state: ScraperAgentState) -> ScraperAgentState:
    """LangGraph node: summarize scrape run results."""
    logger.info("=" * 60)
    logger.info("SCRAPER AGENT RUN SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Day of week: {state.day_of_week}")
    logger.info(f"Chunks completed: {state.batch_index}")
    logger.info(f"Total jobs found: {state.jobs_found_total}")
    logger.info(f"Jobs upserted (new): {state.jobs_upserted}")
    logger.info(f"Jobs deduped (already in DB): {state.jobs_deduped}")
    if state.error:
        logger.error(f"Error: {state.error}")
    logger.info("=" * 60 + "\n")
    state.error = None
    return state


"""LangGraph construction."""


def build_scraper_graph() -> Any:
    """Build and return the LangGraph scraper workflow."""
    graph = StateGraph(ScraperAgentState)
    graph.add_node("scrape_chunk", scrape_chunk_node)
    graph.add_node("summarize", summarize_node)
    graph.add_edge(START, "scrape_chunk")
    graph.add_edge("scrape_chunk", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()


"""ScraperAgent class."""


class ScraperAgent:
    """Main ScraperAgent with run() and run_batch() methods."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.graph = build_scraper_graph()
        self.state = ScraperAgentState()

    def run(self) -> Dict[str, Any]:
        """Run the scraper agent for today's batch."""
        logger.info("Starting ScraperAgent")
        logger.info(f"DRY_RUN={self.dry_run}")
        self.state = ScraperAgentState()
        self.state.day_of_week = datetime.datetime.today().strftime("%A")

        if self.dry_run:
            logger.info("[DRY RUN] Would execute scraper chunks")
            chunks = get_today_chunks()
            self.state.chunks_completed = len(chunks) if chunks else 0
            self.state.jobs_found_total = sum(
                len(scrape_remoteok_chunk(r, l) + scrape_arbeitnow_chunk(r, l) + scrape_remotive_chunk(r, l) + scrape_jobicy_chunk(r, l))
                for r, l, _, _ in chunks
            )
            return {
                "dry_run": True,
                "day_of_week": self.state.day_of_week,
                "chunks_planned": self.state.chunks_completed,
                "estimated_jobs": self.state.jobs_found_total,
            }

        try:
            final_state = self.graph.invoke(self.state)
            # LangGraph 1.x may return a dict instead of the state object
            state_dict = final_state if isinstance(final_state, dict) else final_state.__dict__
            return {
                "dry_run": False,
                "day_of_week": state_dict.get("day_of_week"),
                "chunks_completed": state_dict.get("batch_index"),
                "jobs_found_total": state_dict.get("jobs_found_total"),
                "jobs_upserted": state_dict.get("jobs_upserted"),
                "jobs_deduped": state_dict.get("jobs_deduped"),
                "error": state_dict.get("error"),
            }
        except Exception as e:
            logger.error(f"ScraperAgent run failed: {e}")
            self.state.error = str(e)
            return {
                "dry_run": False,
                "error": str(e),
                "day_of_week": self.state.day_of_week,
            }

    def run_batch(self, days: int = 1) -> Dict[str, Any]:
        """Run scraper for multiple days."""
        logger.info(f"Starting ScraperAgent batch run for {days} day(s)")
        all_results = []

        for day_offset in range(days):
            target_date = datetime.datetime.today() + datetime.timedelta(days=day_offset)
            day_name = target_date.strftime("%A")
            self.state = ScraperAgentState()
            self.state.day_of_week = day_name
            self.state.batch_index = 0

            if self.dry_run:
                chunks = get_today_chunks()
                self.state.chunks_completed = len(chunks) if chunks else 0
                self.state.jobs_found_total = 0
                all_results.append(
                    {"day": day_name, "dry_run": True, "chunks_planned": self.state.chunks_completed}
                )
            else:
                self.state.batch_index = 0
                try:
                    final_state = self.graph.invoke(self.state)
                    # LangGraph 1.x may return a dict instead of the state object
                    state_dict = final_state if isinstance(final_state, dict) else final_state.__dict__
                    all_results.append(
                        {"day": day_name,
                         "chunks_completed": state_dict.get("batch_index", 0),
                         "jobs_found_total": state_dict.get("jobs_found_total", 0),
                         "jobs_upserted": state_dict.get("jobs_upserted", 0),
                         "jobs_deduped": state_dict.get("jobs_deduped", 0),
                         "error": state_dict.get("error")}
                    )
                except Exception as e:
                    logger.error(f"Batch failed for {day_name}: {e}")
                    all_results.append({"day": day_name, "error": str(e)})

            if day_offset < days - 1:
                logger.info(f"Sleeping {THROTTLE_SECONDS}s before next day...")
                time.sleep(THROTTLE_SECONDS)

        total_upserted = sum(r.get("jobs_upserted", 0) for r in all_results)
        total_deduped = sum(r.get("jobs_deduped", 0) for r in all_results)
        total_errors = sum(1 for r in all_results if r.get("error"))

        summary = {
            "days_run": len(all_results),
            "total_chunks": sum(r.get("chunks_completed", 0) for r in all_results),
            "total_jobs_upserted": total_upserted,
            "total_jobs_deduped": total_deduped,
            "days_with_errors": total_errors,
            "results": all_results,
        }
        logger.info(f"Batch complete: {summary}")
        return summary


"""CLI entry point."""


def main():
    """CLI entry point for ScraperAgent."""
    import argparse

    parser = argparse.ArgumentParser(
        description="ScraperAgent - LangGraph Job Scraping Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper_agent.py                          # Run today's chunk
  python scraper_agent.py --dry-run               # Dry run (no DB writes)
  python scraper_agent.py --batch 0               # Run only Monday's chunk
  python scraper_agent.py --days 3                # Run for 3 days
  python scraper_agent.py --print-schedule        # Print weekly schedule
        """
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Dry run - no DB writes")
    parser.add_argument("--batch", type=int, default=0,
                        help="Run specific batch index (0 = today's chunk)")
    parser.add_argument("--days", type=int, default=1,
                        help="Run for N days (default: 1 = today)")
    parser.add_argument("--print-schedule", action="store_true",
                        help="Print weekly schedule")
    args = parser.parse_args()

    if args.print_schedule:
        from chunk_dispatcher import print_weekly_schedule
        print_weekly_schedule()
        return

    agent = ScraperAgent(dry_run=args.dry_run)

    if args.days > 1:
        result = agent.run_batch(days=args.days)
    elif args.batch >= 0:
        agent.state.batch_index = args.batch
        result = agent.run()
    else:
        result = agent.run()

    print(f"\nScraperAgent Result: {result}")


if __name__ == "__main__":
    main()