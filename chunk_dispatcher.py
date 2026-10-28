"""============================================================
  Chunk Dispatcher - Day-of-Week Job Scraping Schedule
  ============================================================

  Maps day-of-week to role/location/experience band chunks
  for the ScraperAgent. Each chunk is a (roles, locations,
  experience_bands) tuple that gets processed sequentially.

  Usage:
    from chunk_dispatcher import get_today_chunks, WEEKLY_SCHEDULE
    chunks = get_today_chunks()  # Get today's batch
    for chunk in chunks:
        scraper.run_chunk(chunk)
"""

import datetime
from typing import List, Tuple, Dict

# ── Weekly Chunk Schedule ──────────────────────────────────
# Each entry: (day_name, roles, locations, experience_bands)
# Roles are job titles to target, locations are cities,
# experience_bands are ENTRY, MID_JUNIOR, MID_SENIOR, SENIOR,
# STAFF_LEAD, PRINCIPAL_EXEC

WEEKLY_SCHEDULE: Dict[str, Tuple[List[str], List[str], List[str]]] = {
    "Monday": (
        ["AI Engineer", "ML Engineer", "Forward Deployed Engineer", "GenAI Engineer"],
        ["Bangalore", "Hyderabad", "Chennai", "Noida", "Gurgaon", "Pune", "Kolkata", "Remote"],
        ["ENTRY", "MID_JUNIOR"],
    ),
    "Tuesday": (
        ["AEM Developer", "Salesforce Developer", "Workday Developer"],
        ["Bangalore", "Hyderabad", "Chennai", "Noida", "Gurgaon", "Pune", "Remote"],
        ["MID_JUNIOR", "MID_SENIOR"],
    ),
    "Wednesday": (
        ["Backend Engineer", "DevOps Engineer", "Cloud Engineer"],
        ["Bangalore", "Hyderabad", "Chennai", "Noida", "Gurgaon", "Pune", "Kolkata", "Remote"],
        ["ENTRY", "MID_JUNIOR", "MID_SENIOR"],
    ),
    "Thursday": (
        ["Frontend Engineer", "Android Engineer", "iOS Engineer", "Flutter Developer"],
        ["Bangalore", "Hyderabad", "Chennai", "Noida", "Gurgaon", "Pune", "Kolkata", "Remote"],
        ["ENTRY", "MID_JUNIOR"],
    ),
    "Friday": (
        ["Data Engineer", "Data Scientist", "Analytics Engineer"],
        ["Bangalore", "Hyderabad", "Chennai", "Remote"],
        ["MID_SENIOR", "SENIOR"],
    ),
    "Saturday": (
        ["Site Reliability Engineer", "Platform Engineer"],
        ["Bangalore", "Hyderabad", "Remote"],
        ["SENIOR", "STAFF_LEAD"],
    ),
    "Sunday": (
        # Long-tail / refresh top roles
        ["Product Engineer", "Technical Writer", "QA Engineer", "DevRel Associate"],
        ["Bangalore", "Hyderabad", "Remote"],
        ["ENTRY", "MID_JUNIOR"],
    ),
}


def get_today_chunks() -> List[Tuple[List[str], List[str], List[str]]]:
    """Return the chunks for today's day-of-week.

    Returns a list of (roles, locations, experience_bands) tuples.
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
                ["Bangalore", "Remote"],
                ["ENTRY"],
            )
        )
    return chunks


def get_schedule_for_day(day_name: str) -> Tuple[List[str], List[str], List[str]]:
    """Return the chunk for a specific day name."""
    if day_name in WEEKLY_SCHEDULE:
        return WEEKLY_SCHEDULE[day_name]
    return WEEKLY_SCHEDULE["Sunday"]


def print_weekly_schedule():
    """Print the entire week's schedule (for debugging/admin)."""
    print("=== Weekly Scraper Chunk Schedule ===")
    for day, (roles, locations, experience) in WEEKLY_SCHEDULE.items():
        print(f"\n{day}:")
        print(f"  Roles: {', '.join(roles)}")
        print(f"  Locations: {', '.join(locations)}")
        print(f"  Experience: {', '.join(experience)}")
    print("\n=== End of Schedule ===")


if __name__ == "__main__":
    print_weekly_schedule()