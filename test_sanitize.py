"""Offline unit checks (no API keys needed). Run: python test_sanitize.py"""
from sheets_client import normalize_skills, parse_experience, normalize_work_pref, is_valid_email, sanitize_subscriber

assert normalize_skills("React, TypeScript, Node.js") == ["React", "TypeScript", "Node.js"]
assert normalize_skills("React, react,  ") == ["React"]
assert parse_experience("5 years") == 5 and parse_experience("") == 0
assert normalize_work_pref("remote") == "Remote" and normalize_work_pref("bogus") == "Remote"
assert is_valid_email("jane.doe@example.com") and not is_valid_email("bad@")
row = {"Status": "Active", "Email Address": "jane@example.com", "Primary Role": "FE",
       "Years of Experience": "5", "Key Skillsets": "React, TypeScript", "Work Preference": "Remote"}
s = sanitize_subscriber(row, 2)
assert s["_valid"] and s["_skills_list"] == ["React", "TypeScript"] and s["_experience_years"] == 5
bad = sanitize_subscriber({**row, "Email Address": "x"}, 3)
assert not bad["_valid"] and bad["_invalid_reason"] == "invalid-email"
print("All sanitize tests passed ✅")
