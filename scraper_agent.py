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
import re
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
from telemetry import record_scrape, send_report

FAILED_JOBS: List[str] = []
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ✅ CIRCUIT BREAKER PATTERN FOR FAULT ISOLATION
class CircuitBreaker:
    """Circuit breaker pattern for fault isolation per-agent.

    Prevents cascading failures by tripping after N consecutive failures,
    and allows half-open recovery after a timeout.
    """

    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"      # Failing, skip calls
    HALF_OPEN = "HALF_OPEN"  # Testing recovery

    def __init__(self, failure_threshold: int = 3, reset_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time: float = 0.0
        self.success_count = 0

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        if self.state == self.OPEN:
            if self.last_failure_time and \
               (time.time() - self.last_failure_time) > self.reset_timeout:
                self.state = self.HALF_OPEN
                self.success_count = 0
            else:
                raise CircuitOpenError(f"Circuit breaker OPEN for {func.__name__}")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Reset failure count on success."""
        self.failure_count = 0
        if self.state == self.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 2:
                self.state = self.CLOSED
                self.success_count = 0

    def _on_failure(self):
        """Track failure and potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = self.OPEN
            logger.warning(
                f"Circuit breaker OPEN after {self.failure_count} consecutive failures"
            )

    def force_open(self):
        """Force circuit open (emergency)."""
        self.state = self.OPEN
        self.last_failure_time = time.time()

    def force_close(self):
        """Force circuit close (bypass)."""
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and call is blocked."""
    pass


# ✅ AGENT CIRCUIT BREAKERS REGISTRY
# Per-agent circuit breakers to prevent cascading failures
AGENT_CIRCUIT_BREAKERS: Dict[str, CircuitBreaker] = {
    "remoteok": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "arbeitnow": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "naukri": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "linkedin": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "remotive": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "jobicy": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "seek": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "instahyre": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "bayt": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "builtin": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "ai_companies": CircuitBreaker(failure_threshold=3, reset_timeout=120),
    "company_careers": CircuitBreaker(failure_threshold=3, reset_timeout=120),
}


# ✅ PER-AGENT SUCCESS RATE TRACKING
# Tracks success/failure metrics for adaptive failover decisions
AGENT_METRICS: Dict[str, Dict[str, Any]] = {
    name: {"successes": 0, "failures": 0, "total_calls": 0, "last_failure": None}
    for name in AGENT_CIRCUIT_BREAKERS.keys()
}


def track_agent_metrics(agent_name: str, success: bool):
    """Track per-agent success/failure metrics for adaptive failover.

    Args:
        agent_name: Name of the scraper agent
        success: Whether the scrape was successful
    """
    if agent_name in AGENT_METRICS:
        metrics = AGENT_METRICS[agent_name]
        metrics["total_calls"] += 1
        if success:
            metrics["successes"] += 1
        else:
            metrics["failures"] += 1
            metrics["last_failure"] = datetime.datetime.now().isoformat()


def get_agent_success_rate(agent_name: str) -> float:
    """Get success rate (0.0 to 1.0) for an agent.

    Used by the supervisor to prioritize reliable agents.

    Args:
        agent_name: Name of the scraper agent

    Returns:
        Success rate as a float between 0.0 and 1.0
    """
    if agent_name in AGENT_METRICS:
        metrics = AGENT_METRICS[agent_name]
        if metrics["total_calls"] > 0:
            return metrics["successes"] / metrics["total_calls"]
    return 0.5  # Default neutral rate


def prioritize_agents_by_metrics() -> List[str]:
    """Agents sorted by success rate (best first) for dynamic prioritization.

    Returns:
        List of agent names sorted by reliability (highest success rate first)
    """
    rates = []
    for name in AGENT_METRICS:
        rate = get_agent_success_rate(name)
        rates.append((name, rate))
    rates.sort(key=lambda x: x[1], reverse=True)
    return [name for name, _ in rates]


# ✅ EXPONENTIAL BACKOFF HELPER
def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """Calculate exponential backoff delay with jitter.

    Args:
        attempt: Retry attempt number (0-indexed)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds

    Returns:
        Delay in seconds before next retry
    """
    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
    return delay


def retry_with_backoff(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple = (Exception,),
    backoff_factor: float = 2.0,
) -> Any:
    """Retry function with exponential backoff and jitter.

    Wraps a function call with automatic retries on failure,
    using increasing delays between attempts to avoid thundering herd.

    Args:
        func: Function to execute
        *args: Arguments to pass to func
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        exceptions: Exception types to catch and retry on
        backoff_factor: Multiplier for delay increase between attempts

    Returns:
        Result of func() if successful

    Raises:
        The original exception if all retries are exhausted
    """
    for attempt in range(max_retries + 1):
        try:
            return func(*args)
        except exceptions as e:
            if attempt < max_retries:
                delay = exponential_backoff(attempt, base_delay, 60.0)
                logger.warning(
                    f"Attempt {attempt + 1} failed for {func.__name__}: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"All {max_retries + 1} attempts failed for {func.__name__}: {e}"
                )
                raise
    raise RuntimeError(f"Function {func.__name__} failed after {max_retries + 1} retries")
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


def remove_about_sections(parts):
    keep = []
    skip_prefixes = (
        "about us", "about the company", "about company", "our company",
        "who we are", "company overview", "overview", "our mission",
        "our story", "company details", "corporate information"
    )
    for part in parts:
        p = part.strip()
        if not p:
            continue
        low = p.lower()
        if any(low.startswith(sp) for sp in skip_prefixes):
            continue
        keep.append(p)
    return " ".join(keep)


def extract_text_section(description_text: str, section_keyword: str, max_chars: int = 300) -> str:
    """Extract text from a section of the description following a keyword.

    Args:
        description_text: Clean job description text.
        section_keyword: Keyword to search for (e.g., 'responsibilities', 'salary').
        max_chars: Maximum characters to return.

    Returns:
        Extracted text from the section.
    """
    if not description_text:
        return ""

    # Find the section keyword
    pattern = re.compile(re.escape(section_keyword), re.IGNORECASE)
    match = pattern.search(description_text)
    if not match:
        return ""

    # Get text after the keyword
    after_keyword = description_text[match.end():]

    # Find the end of this section (look for known next sections)
    next_keywords = ["salary", "compensation", "perks", "benefits", "requirements", "qualifications"]
    end_pos = len(after_keyword)
    for kw in next_keywords:
        idx = after_keyword.lower().index(kw) if kw in after_keyword.lower() else len(after_keyword)
        if idx < end_pos:
            end_pos = idx

    extracted = after_keyword[:end_pos].strip()
    extracted = re.sub(r"\s+", " ", extracted).strip()
    return extracted[:max_chars]


def truncate_to_complete_sentence(text: str) -> str:
    if not text:
        return text
    last_end = -1
    for m in re.finditer(r"[.!?](?:\s|$)", text):
        last_end = m.end()
    if last_end <= 0:
        return text.strip()
    return text[:last_end].strip()


def prepare_job_description(description_text: str, location: str) -> str:
    desc = clean_description(description_text or "", 1200)
    desc = remove_about_sections(desc)
    desc = truncate_to_complete_sentence(desc)
    if location and location.lower() not in ("remote", "unknown", ""):
        desc = (desc + " Location: " + location + ".").strip()
    return desc


"""Scraper sources - company career portals only."""
def scrape_company_careers_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape top company career pages for jobs matching roles/locations.
    Uses COMPANY_LIST and iterates through Greenhouse/Lever APIs for each company.
    Returns list of job dicts. If no jobs found, returns empty list.
    """
    jobs = []
    seen_urls: set = set()
    for company in COMPANY_LIST:
        for slug in _slug_variants(company):
            found = []
            for fetcher in (scrape_greenhouse_board, scrape_lever_board):
                try:
                    found = fetcher(slug, roles, locations)
                except Exception:
                    found = []
                if found:
                    break
            for j in found:
                url = j.get("apply_url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                j["company"] = company
            jobs.extend(found)
    # Deduplicate by apply_url
    seen = set(); uniq = []
    for j in jobs:
        if j.get("apply_url") in seen: continue
        seen.add(j["apply_url"]); uniq.append(j)
    logger.info(f"Company careers: found {len(uniq)} matching jobs across {len(COMPANY_LIST)} companies")
    return uniq


"""DB helpers."""
def deduplicate_and_upsert(jobs: List[Dict]) -> Tuple[int, int]:
    """Validate, deduplicate, then upsert jobs to Supabase.

    Mandatory fields (title, company, location, description_text, apply_url)
    must be present. Deduplication happens BEFORE any DB write.
    Returns (new_jobs_count, deduped_count).
    """
    if not jobs:
        return 0, 0

    # 1. Validate + format
    valid: List[Dict] = []
    for job in jobs:
        title = (job.get("title") or "").strip()
        company = (job.get("company") or "").strip()
        location = (job.get("location") or "").strip()
        apply_url = (job.get("apply_url") or "").strip()
        description = prepare_job_description(job.get("description_text", ""), location)
        if not (title and company and location and description and apply_url):
            continue
        # ignore remote/no-location jobs
        if location.lower() in ("remote", "unknown", ""):
            continue
        if len(description) < 20:
            continue
        # normalize location: keep only the first location in the field
        loc_parts = [x.strip() for x in re.split(r"[,;]", location) if x.strip()]
        if loc_parts:
            location = loc_parts[0]
        job["title"] = title
        job["company"] = company
        job["location"] = location
        job["apply_url"] = apply_url
        job["description_text"] = description
        skills = job.get("required_skills") or []
        if isinstance(skills, str):
            skills = [x.strip() for x in skills.split(",") if x.strip()]
        job["required_skills"] = skills
        for k in ("min_experience", "max_experience"):
            v = job.get(k)
            if v is not None:
                try:
                    job[k] = int(v)
                except (ValueError, TypeError):
                    job[k] = None
        valid.append(job)

    # 2. Deduplicate in memory (before any DB write)
    seen_urls: set = set()
    seen_keys: set = set()
    unique: List[Dict] = []
    for job in valid:
        url = job["apply_url"]
        key = (job["title"].lower(), job["company"].lower(), job["location"].lower())
        if url in seen_urls or key in seen_keys:
            continue
        seen_urls.add(url)
        seen_keys.add(key)
        unique.append(job)

    deduped_count = len(jobs) - len(unique)
    if not unique:
        return 0, deduped_count

    # 3. Upsert only after deduplication
    conn = get_db_connection()
    if conn is None:
        logger.error("No DB connection available")
        return 0, deduped_count

    new_count = 0
    try:
        with conn.cursor() as cur:
            for job in unique:
                apply_url = job["apply_url"]
                existing = find_existing_job(cur, apply_url=apply_url)
                if existing:
                    description = job["description_text"]
                    embedding = None
                    if description and GEMINI_API_KEY:
                        try:
                            emb = get_gemini_embedding(description)
                            embedding = emb.embedding if emb else None
                        except Exception as e:
                            logger.error(f"Embedding error: {e}")
                    # Refresh fields (cleaned description, etc.) on existing rows
                    try:
                        upsert_job(
                            cur,
                            title=job["title"],
                            company=job["company"],
                            location=job["location"],
                            work_style=job.get("work_style", ""),
                            min_experience=job.get("min_experience"),
                            max_experience=job.get("max_experience"),
                            required_skills=job.get("required_skills", []),
                            description_text=description,
                            apply_url=apply_url,
                            embedding=embedding,
                            posted_at=job.get("posted_at"),
                            is_active=True,
                            roles_responsibilities=job.get("roles_responsibilities", ""),
                            salary_compensation=job.get("salary_compensation", ""),
                        )
                    except Exception as e:
                        logger.error(f"Update failed for {apply_url}: {e}")
                    deduped_count += 1
                    continue
                description = job["description_text"]
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
                        title=job["title"],
                        company=job["company"],
                        location=job["location"],
                        work_style=job.get("work_style", ""),
                        min_experience=job.get("min_experience"),
                        max_experience=job.get("max_experience"),
                        required_skills=job.get("required_skills", []),
                        description_text=description,
                        apply_url=apply_url,
                        embedding=embedding,
                        posted_at=job.get("posted_at"),
                        is_active=True,
                        roles_responsibilities=job.get("roles_responsibilities", ""),
                        salary_compensation=job.get("salary_compensation", ""),
                    )
                    new_count += 1
                    logger.info(f"Upserted new job: {job['title']} at {job['company']}")
                except Exception as e:
                    logger.error(f"Upsert failed for {apply_url}: {e}")
                    try:
                        FAILED_JOBS.append(apply_url)
                    except Exception:
                        pass
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
                if not any(k in location.lower() for k in ("bengaluru", "hyderabad", "bangalore", "mumbai", "delhi", "pune", "chennai")):
                    continue
                try:
                    url = f"https://www.naukri.com/{role.lower().replace(' ', '-')}-jobs-{location.lower().replace(' ', '-')}"
                    resp = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
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
                            "work_style": "Remote" if "remote" in title.lower() else "Onsite",
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
                    resp = requests.get(search_url, headers=headers, timeout=5)
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
                "required_skills": [r for r in roles if r.split()[0].lower() in title.lower()] or ([roles[0]] if roles else []),
                "description_text": clean_description(j.get("description", ""), 500),
                "apply_url": url,
                "posted_at": j.get("publication_date"),
                "region": "US",
                "roles_responsibilities": "",
                "salary_compensation": "",
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
                "required_skills": [r for r in roles if r.split()[0].lower() in title.lower()] or ([roles[0]] if roles else []),
                "description_text": clean_description(j.get("jobDescription", ""), 500),
                "apply_url": url,
                "posted_at": j.get("pubDate"),
                "region": "US",
                "roles_responsibilities": "",
                "salary_compensation": "",
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
                        jobs.append({"title": title[:120], "company": "", "location": loc, "work_style": "Remote" if "remote" in title.lower() else "Onsite", "min_experience": None, "max_experience": None, "required_skills": [role], "description_text": "", "apply_url": full, "posted_at": None, "region": "APAC", "roles_responsibilities": "", "salary_compensation": ""})
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
                        jobs.append({"title": title[:120], "company": "", "location": loc, "work_style": "Remote" if "remote" in title.lower() else "Onsite", "min_experience": None, "max_experience": None, "required_skills": [role], "description_text": "", "apply_url": full, "posted_at": None, "region": "India", "roles_responsibilities": "", "salary_compensation": ""})
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
                        jobs.append({"title": title[:120], "company": "", "location": loc, "work_style": "Remote" if "remote" in title.lower() else "Onsite", "min_experience": None, "max_experience": None, "required_skills": [role], "description_text": "", "apply_url": full, "posted_at": None, "region": "MEA", "roles_responsibilities": "", "salary_compensation": ""})
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
                        jobs.append({"title": title[:120], "company": "", "location": loc, "work_style": "Remote" if "remote" in title.lower() else "Onsite", "min_experience": None, "max_experience": None, "required_skills": [role], "description_text": "", "apply_url": full, "posted_at": None, "region": "US", "roles_responsibilities": "", "salary_compensation": ""})
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


COMPANY_LIST = [
    "NVIDIA", "Advanced Micro Devices", "Intel Corporation", "Broadcom", "Marvell Technology",
    "Qualcomm", "Microsoft Corporation", "Alphabet", "Amazon Web Services", "Meta Platforms",
    "Oracle Corporation", "IBM Corporation", "OpenAI", "Anthropic", "Palantir Technologies",
    "Snowflake", "Databricks", "Salesforce", "ServiceNow", "Adobe", "C3.ai", "UiPath",
    "Scale AI", "Perplexity AI", "Midjourney", "Tesla", "Cruise", "Waymo", "Netradyne",
    "Persistent Systems", "Infosys", "Tata Consultancy Services", "Wipro", "HCLTech",
    "LTIMindtree", "Tech Mahindra", "Tata Elxsi", "Cognizant India", "Fractal Analytics",
    "Sarvam AI", "Yellow.ai", "Uniphore", "CoRover.ai", "InMobi", "Mu Sigma",
    "IdeaForge", "Cropin", "Gramener",
    # Additional high-value AI companies from Top 100 CSV
    "Mistral AI", "Perplexity AI", "Sarvam AI", "Yellow.ai", "Glean", "Harvey",
    "Cursor", "Devin", "Sierra", "Anduril Industries", "Shield AI",
]


def _slug_variants(name: str) -> List[str]:
    base = name.lower().replace("&", "and")
    variants = set()
    variants.add(base.replace(" ", "").replace(".", "").replace(",", ""))
    variants.add(base.replace(" ", "-").replace(".", "").replace(",", ""))
    return [v for v in variants if v]


def _clean_html_text(html: str) -> str:
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
        return clean_description(BeautifulSoup(html, "html.parser").get_text(" ", strip=True), 500)
    except Exception:
        return clean_description(html, 500)



        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return jobs
        data = resp.json().get("jobs", [])
        role_l = [r.lower() for r in roles]
        loc_l = [l.lower() for l in locations]
        for j in data:
            title = (j.get("title") or "").strip()
            if not title or not any(r.split()[0] in title.lower() for r in role_l):
                continue
            loc_obj = j.get("location")
            loc_name = loc_obj.get("name", "") if isinstance(loc_obj, dict) else (loc_obj or "")
            if loc_l and loc_name and not any(l.split()[0] in loc_name.lower() for l in loc_l):
                if "remote" not in loc_name.lower():
                    continue
            desc = _clean_html_text(j.get("content", "") or "")
            url_apply = j.get("absolute_url") or j.get("url") or ""
            if not url_apply:
                continue
            ws = "Remote" if "remote" in (title + " " + loc_name).lower() else "Onsite"
            jobs.append({
                "title": title,
                "company": slug.replace("-", " ").title(),
                "location": loc_name or "Unknown",
                "work_style": ws,
                "min_experience": None,
                "max_experience": None,
                "required_skills": [r for r in roles if r.split()[0].lower() in title.lower()] or ([roles[0]] if roles else []),
                "description_text": desc or f"{title} at {slug}",
                "apply_url": url_apply,
                "posted_at": j.get("updated_at"),
                "region": "US",
                "roles_responsibilities": "",
                "salary_compensation": "",
            })
        return jobs
    except Exception as e:
        logger.debug(f"Greenhouse {slug} failed: {e}")
        return jobs


def scrape_lever_board(slug: str, roles: List[str], locations: List[str]) -> List[Dict]:
    jobs = []
    try:
        import requests
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return jobs
        data = resp.json()
        if not isinstance(data, list):
            return jobs
        role_l = [r.lower() for r in roles]
        loc_l = [l.lower() for l in locations]
        for j in data:
            title = (j.get("text") or "").strip()
            if not title or not any(r.split()[0] in title.lower() for r in role_l):
                continue
            cats = j.get("categories", {}) or {}
            loc_name = cats.get("location", "") or ""
            if loc_l and loc_name and not any(l.split()[0] in loc_name.lower() for l in loc_l):
                if "remote" not in loc_name.lower():
                    continue
            desc = _clean_html_text(j.get("description", "") or j.get("descriptionPlain", "") or "")
            url_apply = j.get("hostedUrl") or j.get("applyUrl") or ""
            if not url_apply:
                continue
            ws = "Remote" if "remote" in (title + " " + loc_name).lower() else "Onsite"
            jobs.append({
                "title": title,
                "company": slug.replace("-", " ").title(),
                "location": loc_name or "Unknown",
                "work_style": ws,
                "min_experience": None,
                "max_experience": None,
                "required_skills": [r for r in roles if r.split()[0].lower() in title.lower()] or ([roles[0]] if roles else []),
                "description_text": desc or f"{title} at {slug}",
                "apply_url": url_apply,
                "posted_at": j.get("createdAt"),
                "region": "US",
                "roles_responsibilities": "",
                "salary_compensation": "",
            })
        return jobs
    except Exception as e:
        logger.debug(f"Lever {slug} failed: {e}")
        return jobs


def scrape_company_careers_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    jobs = []
    seen_urls: set = set()
    for company in COMPANY_LIST:
        for slug in _slug_variants(company):
            found = []
            for fetcher in (scrape_greenhouse_board, scrape_lever_board):
                try:
                    found = fetcher(slug, roles, locations)
                except Exception:
                    found = []
                if found:
                    break
            for j in found:
                url = j.get("apply_url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                j["company"] = company
                jobs.append(j)
            if found:
                break
            try:
                import time
                time.sleep(0.1)
            except Exception:
                pass
    logger.info(f"Company careers: {len(jobs)} matching jobs")
    return jobs


# AI Companies Career Portals (from Top 100 Ai companies.csv)
AI_COMPANIES_CAREERS: List[Tuple[str, str]] = [
    ("OpenAI", "https://openai.com/careers"),
    ("Anthropic", "https://anthropic.com/careers"),
    ("Google DeepMind", "deepmind.google/about/careers"),
    ("xAI", "x.ai/careers"),
    ("Meta AI", "metacareers.com"),
    ("Mistral AI", "mistral.ai/careers"),
    ("Cohere", "https://cohere.com/careers"),
    ("AI21 Labs", "https://ai21.com/careers"),
    ("Inflection AI", "https://inflection.ai/careers"),
    ("Stability AI", "https://stability.ai/careers"),
    ("Aleph Alpha", "https://aleph-alpha.com/careers"),
    ("Sakana AI", "https://sakana.ai/careers"),
    ("Poolside", "https://poolside.ai/careers"),
    ("Magic", "https://magic.dev/careers"),
    ("Essential AI", "https://essential.ai/careers"),
    ("NVIDIA", "https://nvidia.com/en-us/about-nvidia/careers"),
    ("Databricks", "https://databricks.com/company/careers"),
    ("Scale AI", "https://scale.com/careers"),
    ("Hugging Face", "https://huggingface.co/jobs"),
    ("Snowflake", "https://careers.snowflake.com"),
    ("Cerebras Systems", "https://cerebras.ai/careers"),
    ("Groq", "https://groq.com/careers"),
    ("SambaNova Systems", "https://sambanova.ai/careers"),
    ("Graphcore", "https://graphcore.ai/careers"),
    ("Together AI", "https://together.ai/careers"),
    ("Anyscale", "https://anyscale.com/careers"),
    ("Weights & Biases", "https://wandb.ai/careers"),
    ("Pinecone", "https://pinecone.io/careers"),
    ("Weaviate", "https://weaviate.io/careers"),
    ("LangChain", "https://langchain.com/careers"),
    ("Modal", "https://modal.com/careers"),
    ("Replicate", "https://replicate.com/careers"),
    ("Fireworks AI", "https://fireworks.ai/careers"),
    ("CoreWeave", "https://coreweave.com/careers"),
    ("Lambda", "https://lambdalabs.com/careers"),
    ("Microsoft AI", "https://careers.microsoft.com"),
    ("Amazon AWS AI", "https://amazon.jobs"),
    ("Apple AI/ML", "https://jobs.apple.com"),
    ("Salesforce AI", "https://careers.salesforce.com"),
    ("Adobe", "https://careers.adobe.com"),
    ("ServiceNow", "https://careers.servicenow.com"),
    ("Oracle AI", "https://oracle.com/careers"),
    ("IBM watsonx", "https://www.ibm.com/watsonx/careers"),
    ("SAP AI", "https://www.sap.com/index.html#/gem/ai/careers"),
    ("Salesforce", "https://careers.salesforce.com"),
    ("Adobe", "https://careers.adobe.com"),
    ("ServiceNow", "https://careers.servicenow.com"),
    ("Oracle", "https://oracle.com/careers"),
    ("IBM", "https://www.ibm.com/careers"),
    ("SAP", "https://www.sap.com/index.html#/gem/ai/careers"),
    ("Accenture", "https://www.accenture.com/us-en-careers"),
    ("Tata Elxsi", "https://tataelxsi.com/careers"),
    ("Tiger Analytics", "https://tigeranalytics.com/careers"),
    ("LatentView Analytics", "https://latentview.com/careers"),
    ("Gnani.ai", "https://gnani.ai/careers"),
    ("Neysa", "https://neysa.ai/careers"),
    ("Wayve", "https://wayve.ai/careers"),
    ("Synthesia", "https://synthesia.io/careers"),
    ("Isomorphic Labs", "https://isomorphiclabs.com/careers"),
    ("ElevenLabs", "https://elevenlabs.io/careers"),
    ("PolyAI", "https://poly.ai/careers"),
    ("Darktrace", "https://darktrace.com/careers"),
    ("BenevolentAI", "https://benevolent.com/careers"),
    ("Tractable", "https://tractable.ai/careers"),
    ("Peak", "https://peak.ai/careers"),
    ("Faculty", "https://faculty.ai/careers"),
    ("Quantexa", "https://quantexa.com/careers"),
    ("Speechmatics", "https://speechmatics.com/careers"),
    ("Exscientia", "https://exscientia.ai/careers"),
    ("Multiverse", "https://multiverse.io/careers"),
    ("Robin AI", "https://robinai.com/careers"),
    ("Perplexity AI", "https://perplexity.ai/hub/careers"),
    ("Runway", "https://runwayml.com/careers"),
    ("Midjourney", "https://midjourney.com/careers"),
    ("Glean", "https://glean.com/careers"),
    ("Harvey", "https://harvey.ai/careers"),
    ("Anysphere (Cursor)", "https://cursor.com/careers"),
    ("Cognition (Devin)", "https://cognition.ai/careers"),
    ("Sierra", "https://sierra.ai/careers"),
    ("Figure AI", "https://figure.ai/careers"),
    ("Anduril Industries", "https://anduril.com/careers"),
    ("Shield AI", "https://shield.ai/careers"),
    ("Skydio", "https://skydio.com/careers"),
    ("Suno", "https://suno.com/careers"),
    ("Pika", "https://pika.art/careers"),
    ("Character.AI", "https://character.ai/careers"),
    ("Adept AI", "https://adept.ai/careers"),
    ("Writer", "https://writer.com/careers"),
    ("Jasper", "https://jasper.ai/careers"),
    ("Eightfold AI", "https://eightfold.ai/careers"),
    ("UiPath", "https://uipath.com/company/careers"),
]


def scrape_direct_company_sites(roles: List[str], locations: List[str]) -> List[Dict]:
    jobs = []
    seen_urls: set = set()
    role_l = [r.lower() for r in roles]
    loc_l = [l.lower() for l in locations]

    for company, careers_url in AI_COMPANIES_CAREERS:
        if found_for_company:
            break
        try:
            resp = requests.get(careers_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                title = a.get_text(" ", strip=True)
                href = a["href"]
                if not title or len(title) < 6:
                    continue
            if "job" not in href.lower() and "career" not in href.lower() and "position" not in href.lower() and "opening" not in href.lower():
                continue
            if not any(r.split()[0] in title.lower() for r in role_l):
                continue
            full = href if href.startswith("http") else careers_url.rstrip("/") + "/" + href.lstrip("/")
            if full in seen_urls:
                continue
            loc_name = ""
            parent = a.find_parent()
            if parent:
                txt = parent.get_text(" ", strip=True)
                for l in locations:
                    if l.lower() in txt.lower():
                        loc_name = l
                        break
                if not loc_name:
                    loc_name = locations[0] if locations else "Unknown"
                if loc_l and loc_name and loc_name != "Unknown" and not any(l.split()[0] in loc_name.lower() for l in loc_l):
                    if "remote" not in loc_name.lower():
                        continue
                desc = clean_description(title + " " + company + " " + loc_name, 500)
                ws = "Remote" if "remote" in (title + " " + loc_name).lower() else "Onsite"
            if not title or len(title) < 6:
"title": title[:120],
"company": company,
"location": loc_name,
"work_style": ws,
"min_experience": None,
            "max_experience": None,
            "required_skills": [r for r in roles if r.split()[0].lower() in title.lower()] or ([roles[0]] if roles else []),
            "description_text": desc,
            "apply_url": full,
            "posted_at": None,
            "region": "US",
            "roles_responsibilities": "",
            "salary_compensation": "",
            seen_urls.add(full)
            jobs.append(job)
            found_for_company = True
            except Exception:
                continue
            logger.info(f"Direct company sites: {len(jobs)} matching jobs")
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

    all_jobs: List[Dict] = []
    # Filter: only jobs posted within last 48 hours
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)

    # ✅ PARALLEL SCRAPING: Execute all 11 agents in parallel with circuit breaker & retry
    import concurrent.futures

    def _scrape_with_protection(agent_name: str, scraper_func: Callable) -> List[Dict]:
        """Run a scraper agent with circuit breaker and retry protection."""
        cb = AGENT_CIRCUIT_BREAKERS.get(agent_name)
        if cb is None:
            logger.error(f"No circuit breaker configured for {agent_name}")
            track_agent_metrics(agent_name, False)
            return []

        def _inner():
            try:
                cb.call(retry_with_backoff, scraper_func, roles, locations)
                track_agent_metrics(agent_name, True)
                return scraper_func(roles, locations)
            except Exception as e:
                logger.warning(f"{agent_name} scraper failed: {e}")
                track_agent_metrics(agent_name, False)
                return []

        try:
            result = cb.call(_inner)
            return result if result else []
        except CircuitOpenError:
            logger.info(f"Circuit breaker open for {agent_name}, skipping")
            track_agent_metrics(agent_name, False)
            return []

    scraper_map = {
        "remoteok": scrape_remoteok_chunk,
        "arbeitnow": scrape_arbeitnow_chunk,
        "naukri": scrape_naukri_chunk,
        "linkedin": scrape_linkedin_chunk,
        "remotive": scrape_remotive_chunk,
        "jobicy": scrape_jobicy_chunk,
        "ai_companies": scrape_direct_company_sites,
        "company_careers": scrape_company_careers_chunk,
        "seek": scrape_seek_chunk,
        "instahyre": scrape_instahyre_chunk,
        "bayt": scrape_bayt_chunk,
        "builtin": scrape_builtin_chunk,
    }

    results: Dict[str, List[Dict]] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        future_to_agent = {}
        for agent_name, scraper_func in scraper_map.items():
            future = executor.submit(_scrape_with_protection, agent_name, scraper_func)
            future_to_agent[future] = agent_name

        for future in concurrent.futures.as_completed(future_to_agent):
            agent_name = future_to_agent[future]
            try:
                jobs = future.result()
                results[agent_name] = jobs
                logger.info(f"Agent {agent_name}: {len(jobs)} jobs")
            except Exception as e:
                logger.error(f"Agent {agent_name} generated exception: {e}")
                track_agent_metrics(agent_name, False)

    # Aggregate results from all successful agents
    for agent_name in scraper_map:
        if agent_name in results:
            all_jobs.extend(results[agent_name])

    logger.info(f"Chunk total: {len(all_jobs)} jobs aggregated from {len(results)} agents")
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
    direct_company_jobs = scrape_direct_company_sites(roles, locations)
    all_jobs.extend(direct_company_jobs)
    company_jobs = scrape_company_careers_chunk(roles, locations)
    all_jobs.extend(company_jobs)
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
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry the scrape once if any jobs failed")
    parser.add_argument("--report-failures", action="store_true",
                        help="Email a failure report to telemetry recipient")
    args = parser.parse_args()

    if args.print_schedule:
        from chunk_dispatcher import print_weekly_schedule
        print_weekly_schedule()
        return

    global FAILED_JOBS
    FAILED_JOBS = []

    agent = ScraperAgent(dry_run=args.dry_run)

    if args.days > 1:
        result = agent.run_batch(days=args.days)
    elif args.batch >= 0:
        agent.state.batch_index = args.batch
        result = agent.run()
    else:
        result = agent.run()

    # Retry once if requested and there were failures
    if args.retry_failed and FAILED_JOBS:
        print(f"\n[retry] {len(FAILED_JOBS)} failed jobs detected; retrying scrape...")
        FAILED_JOBS.clear()
        result = agent.run()

    print(f"\nScraperAgent Result: {result}")
    if FAILED_JOBS:
        print(f"\n[failures] {len(FAILED_JOBS)} jobs failed:")
        for u in FAILED_JOBS[:50]:
            print(f"  - {u}")
        if args.report_failures:
            try:
                from telemetry import send_report
                send_report("Scraper Failure Report")
            except Exception as e:
                print(f"[telemetry] failed: {e}")
    try:
        record_scrape({**(result if isinstance(result, dict) else {}), "failed_jobs": list(FAILED_JOBS[:50])})
        send_report("Scraper Telemetry Report")
    except Exception as e:
        print(f"[telemetry] failed: {e}")


if __name__ == "__main__":
    main()
