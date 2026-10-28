"""============================================================
  Chunk Dispatcher - Day-of-Week Job Scraping Schedule
  ============================================================

  Maps day-of-week to role/location/experience band chunks
  for the ScraperAgent. Each chunk is a (roles, locations,
  experience_bands, region) tuple that gets processed sequentially.

  Multi-region coverage: US, UK, APAC, MEA
  Latest jobs only: posted within last 48 hours

  Usage:
    from chunk_dispatcher import get_today_chunks, WEEKLY_SCHEDULE
    chunks = get_today_chunks()  # Get today's batch
    for chunk in chunks:
        scraper.run_chunk(chunk)
"""

import datetime
from typing import List, Tuple, Dict

# ── Weekly Chunk Schedule ──────────────────────────────────
# Each entry: (day_name, roles, locations, experience_bands, region)
# Roles are job titles to target, locations are cities,
# experience_bands are ENTRY, MID_JUNIOR, MID_SENIOR, SENIOR,
# STAFF_LEAD, PRINCIPAL_EXEC
# region: US, UK, APAC, MEA, All

WEEKLY_SCHEDULE: Dict[str, Tuple[List[str], List[str], List[str], str]] = {
    "Monday": (
        ["AI Engineer", "ML Engineer", "Forward Deployed Engineer", "GenAI Engineer"],
        ["New York", "San Francisco", "Austin", "Seattle", "Remote"],
        ["ENTRY", "MID_JUNIOR"],
        "US",
    ),
    "Tuesday": (
        ["Backend Engineer", "Frontend Engineer", "DevOps Engineer", "Full Stack Developer"],
        ["London", "Manchester", "Edinburgh", "Remote"],
        ["MID_JUNIOR", "MID_SENIOR"],
        "UK",
    ),
    "Wednesday": (
        ["Data Engineer", "Data Scientist", "Android Engineer", "iOS Engineer", "QA Engineer"],
        ["Bangalore", "Hyderabad", "Chennai", "Pune", "Remote"],
        ["MID_JUNIOR", "MID_SENIOR", "SENIOR"],
        "APAC",
    ),
    "Thursday": (
        ["Cloud Engineer", "Security Engineer", "Platform Engineer", "Site Reliability Engineer"],
        ["Dubai", "Abu Dhabi", "Riyadh", "Remote"],
        ["MID_SENIOR", "SENIOR", "STAFF_LEAD"],
        "MEA",
    ),
    "Friday": (
        ["Product Engineer", "Technical Writer", "DevRel Associate", "UX Designer"],
        ["New York", "London", "Bangalore", "Dubai", "Remote"],
        ["ENTRY", "MID_JUNIOR"],
        "All",
    ),
    "Saturday": (
        ["Junior Developer", "Intern", "Graduate Trainee", "Entry Level Developer"],
        ["New York", "London", "Bangalore", "Dubai", "Remote"],
        ["ENTRY"],
        "All",
    ),
    "Sunday": (
        # Long-tail / refresh top roles across all regions
        ["Product Manager", "Technical Writer", "QA Engineer", "DevRel Associate"],
        ["New York", "London", "Bangalore", "Dubai", "Remote"],
        ["ENTRY", "MID_JUNIOR"],
        "All",
    ),
}


def get_today_chunks() -> List[Tuple[List[str], List[str], List[str], str]]:
    """Return the chunks for today's day-of-week.

    Returns a list of (roles, locations, experience_bands, region) tuples.
    If today is Sunday, returns the Sunday chunk plus a small
    'refresh' chunk of top roles.
    """
    today_name = datetime.datetime.today().strftime("%A")
    if today_name not in WEEKLY_SCHEDULE:
        # Fallback: return Sunday (long-tail) chunk
        today_name = "Sunday"

    chunks = [WEEKLY_SCHEDULE[today_name]]
    # Add a small refresh chunk for Sunday only
    if today_name == "Sunday":
        chunks.append(
            (
                ["Product Engineer", "Technical Writer", "QA Engineer"],
                ["New York", "London", "Bangalore", "Remote"],
                ["ENTRY"],
                "All",
            )
        )
    return chunks


def get_schedule_for_day(day_name: str) -> Tuple[List[str], List[str], List[str], str]:
    """Return the chunk for a specific day name."""
    if day_name in WEEKLY_SCHEDULE:
        return WEEKLY_SCHEDULE[day_name]
    return WEEKLY_SCHEDULE["Sunday"]


def print_weekly_schedule():
    """Print the entire week's schedule (for debugging/admin)."""
    print("=== Weekly Scraper Chunk Schedule ===")
    for day, (roles, locations, experience, region) in WEEKLY_SCHEDULE.items():
        print(f"\n{day} [{region}]:")
        print(f"  Roles: {', '.join(roles)}")
        print(f"  Locations: {', '.join(locations)}")
        print(f"  Experience: {', '.join(experience)}")
    print("\n=== End of Schedule ===")


if __name__ == "__main__":
    print_weekly_schedule()