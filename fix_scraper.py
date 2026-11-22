import re

with open(r'c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py', 'r') as f:
    content = f.read()

# Read the file to check current state
print("Checking file state...")

# The issue: try: at line 1018, except at line 1068, but for loop at 1023 causes syntax error
# Fix: The for loop and its body need to be properly inside the try block,
# and the except needs to be at the right level.

# Let's find and replace the problematic section
# We need to indent the for loop body and ensure proper try-except structure

old_section = """for a in soup.find_all("a", href=True):
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
        job = {
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
        }
        seen_urls.add(full)
        jobs.append(job)
    found_for_company = True
except Exception:
    continue"""

new_section = """for a in soup.find_all("a", href=True):
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
            job = {
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
            }
            seen_urls.add(full)
            jobs.append(job)
        found_for_company = True
except Exception:
    continue"""

if old_section in content:
    content = content.replace(old_section, new_section)
    with open(r'c:\Users\Admin\AndroidStudioProjects\fireflylabz Job alerts\scraper_agent.py', 'w') as f:
        f.write(content)
    print('File fixed successfully')
else:
    print('Old section not found exactly, checking for partial matches...')
    # Try simpler replacement
    if 'for a in soup.find_all("a", href=True):' in content:
        print('Found the for loop pattern')
    else:
        print('for loop pattern not found')