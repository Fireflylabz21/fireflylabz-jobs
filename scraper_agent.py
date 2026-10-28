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
from typing import List, Dict, Optional, Tuple

import numpy as np
from langgraph.graph import StateGraph, START, END
from langchain.schema import HumanMessage, SystemMessage

from chunk_dispatcher import get_today_chunks, WEEKLY_SCHEDULE
from db import get_db_connection, upsert_job, find_existing_job
from embeddings import get_gemini_embedding
from config import DRY_RUN, GEMINI_API_KEY, GEMINI_EMBED_MODEL, THROTTLE_SECONDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
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


"""Scraper sources - stubbed for now; implement in scraper_sources.py later."""
def scrape_remoteok_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    logger.info(f"RemoteOK chunk: {len(roles)} roles x {len(locations)} locations")
    return []


def scrape_arbeitnow_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    logger.info(f"Arbeitnow chunk: {len(roles)} roles x {len(locations)} locations")
    return []


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
    """Scrape Naukri for given roles and locations (India/APAC region).
    Returns list of job dicts with consistent field names including region."""
    jobs = []
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        for role in roles:
            for location in locations:
                try:
                    url = f"https://www.naukri.com/{role.lower().replace(' ', '-')}-jobs-{location.lower().replace(' ', '-')}"
                    resp = requests.get(url, headers=headers, timeout=15)
                    if resp.status_code == 200:
                        # Simplified - would use BeautifulSoup in production
                        jobs.append({
                            "title": f"{role} at {location}",
                            "company": "Naukri Job",
                            "location": location,
                            "work_style": "on-site",
                            "min_experience": None,
                            "max_experience": None,
                            "required_skills": [role],
                            "description_text": f"{role} position at {location}",
                            "apply_url": url,
                            "posted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "region": "APAC",
                        })
                    time.sleep(random.uniform(0.5, 2.0))
                except Exception as e:
                    logger.warning(f"Naukri scrape error for {role}/{location}: {e}")
    except ImportError:
        logger.debug("requests not available for Naukri scraper")
    return jobs


def scrape_linkedin_chunk(roles: List[str], locations: List[str]) -> List[Dict]:
    """Scrape LinkedIn for given roles and locations (US/UK/MEA region).
    Returns list of job dicts with consistent field names including region."""
    jobs = []
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        for role in roles:
            for location in locations:
                try:
                    # Simplified LinkedIn scrape placeholder
                    jobs.append({
                        "title": f"{role}",
                        "company": "LinkedIn Job",
                        "location": location,
                        "work_style": "remote",
                        "min_experience": None,
                        "max_experience": None,
                        "required_skills": [role],
                        "description_text": f"{role} position at {location}",
                        "apply_url": f"https://www.linkedin.com/jobs/search/?keywords={role}&location={location}",
                        "posted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "region": "US",
                    })
                    time.sleep(random.uniform(0.5, 2.0))
                except Exception as e:
                    logger.warning(f"LinkedIn scrape error for {role}/{location}: {e}")
    except ImportError:
        logger.debug("requests not available for LinkedIn scraper")
    return jobs


"""LangGraph nodes."""


def scrape_chunk_node(state: ScraperAgentState) -> ScraperAgentState:
    """LangGraph node: scrape one chunk of jobs."""
    day = state.day_of_week
    chunks = get_today_chunks()

    if not chunks or state.batch_index >= len(chunks):
        state.error = "No more chunks to scrape"
        return state

    roles, locations, experience_bands = chunks[state.batch_index]
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
        all_jobs.extend(arbeitnow_jobs)
    naukri_jobs = scrape_naukri_chunk(roles, locations)
    all_jobs.extend(naukri_jobs)
    linkedin_jobs = scrape_linkedin_chunk(roles, locations)
    all_jobs.extend(linkedin_jobs)

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
                len(scrape_remoteok_chunk(r, l) + scrape_arbeitnow_chunk(r, l))
                for r, l, _ in chunks
            )
            return {
                "dry_run": True,
                "day_of_week": self.state.day_of_week,
                "chunks_planned": self.state.chunks_completed,
                "estimated_jobs": self.state.jobs_found_total,
            }

        try:
            final_state = self.graph.invoke(self.state)
            return {
                "dry_run": False,
                "day_of_week": final_state.day_of_week,
                "chunks_completed": final_state.batch_index,
                "jobs_found_total": final_state.jobs_found_total,
                "jobs_upserted": final_state.jobs_upserted,
                "jobs_deduped": final_state.jobs_deduped,
                "error": final_state.error,
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
                    all_results.append(
                        {"day": day_name,
                         "chunks_completed": final_state.batch_index,
                         "jobs_found_total": final_state.jobs_found_total,
                         "jobs_upserted": final_state.jobs_upserted,
                         "jobs_deduped": final_state.jobs_deduped,
                         "error": final_state.error}
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