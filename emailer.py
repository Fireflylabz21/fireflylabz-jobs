"""Email rendering & delivery via Brevo (primary, 300/day free) + Resend fallback.

Template: Branded cards + hero, mobile-responsive, Outlook-safe (tables + inline CSS).
Brand: Fireflylabz — navy #0F172A + amber #F59E0B.
"""
import html
import time
from typing import Any, Dict, List
import requests
from config import (
    DRY_RUN, FROM_EMAIL, RESEND_API_KEY,
    EMAIL_PROVIDER, BREVO_API_KEY, BREVO_SENDER_EMAIL, BREVO_SENDER_NAME,
    LOGO_LIGHT_URL, LOGO_DARK_URL, BANNER_URL, BRAND_WEBSITE,
)
from unsubscribe import unsubscribe_url

_configured_resend = False

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

BRAND = {
    "name": "FireflyLabz",
    "tagline": "AI Job Alerts",
    "navy": "#0F172A",
    "navy_soft": "#1E293B",
    "amber": "#F59E0B",
    "gold": "#D4AF37",
    "gold_light": "#FDE68A",
    "amber_dark": "#D97706",
    "bg": "#F1F5F9",
    "card_border": "#E2E8F0",
    "muted": "#64748B",
    "dark_bg": "#0B0F1A",
    "dark_card": "#151D2E",
}


def _ensure_resend():
    global _configured_resend
    if not _configured_resend and RESEND_API_KEY:
        import resend
        resend.api_key = RESEND_API_KEY
        _configured_resend = True


def _sender() -> Dict[str, str]:
    """Brevo needs explicit sender email; fall back to parsing FROM_EMAIL."""
    if BREVO_SENDER_EMAIL:
        return {"name": BREVO_SENDER_NAME or "FireflyLabz Jobs",
                "email": BREVO_SENDER_EMAIL.strip()}
    # parse 'Name <email>'
    txt = (FROM_EMAIL or "").strip()
    if "<" in txt and ">" in txt:
        name = txt.split("<")[0].strip().strip('"') or "FireflyLabz Jobs"
        email = txt.split("<")[1].split(">")[0].strip()
        return {"name": name, "email": email}
    return {"name": BREVO_SENDER_NAME or "FireflyLabz Jobs", "email": txt or BREVO_SENDER_EMAIL}


def _send_via_brevo(to_email: str, subject: str, html_body: str,
                    text_body: str, list_unsub: str = "") -> None:
    if not BREVO_API_KEY:
        raise RuntimeError("BREVO_API_KEY missing (Brevo -> Settings -> SMTP & API -> API Keys).")
    sender = _sender()
    if not sender["email"] or "@" not in sender["email"]:
        raise RuntimeError("Set BREVO_SENDER_EMAIL to your Brevo-verified sender.")
    payload: Dict[str, Any] = {
        "sender": sender,
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": text_body,
    }
    headers = {"api-key": BREVO_API_KEY, "Content-Type": "application/json",
               "Accept": "application/json"}
    if list_unsub:
        # Brevo passes custom headers through to Gmail/Outlook one-click button
        headers["List-Unsubscribe"] = f"<{list_unsub}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    r = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Brevo {r.status_code}: {r.text[:300]}")


def _send_via_resend(to_email: str, subject: str, html_body: str,
                     text_body: str, list_unsub: str = "") -> None:
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY missing.")
    _ensure_resend()
    import resend
    params: Dict[str, Any] = {"from": FROM_EMAIL, "to": [to_email],
                              "subject": subject, "html": html_body, "text": text_body}
    if list_unsub:
        params["headers"] = {"List-Unsubscribe": f"<{list_unsub}>",
                             "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    resend.Emails.send(params)


def _e(v: Any) -> str:
    return html.escape(str(v or ""), quote=True)


def _skills_pills(skills) -> str:
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    pills = ""
    for s in (skills or [])[:6]:
        pills += (
            f"<span style=\"display:inline-block;background:#FEF3C7;color:#92400E;"
            f"font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;"
            f"margin:0 6px 6px 0;\">{_e(s)}</span>"
        )
    return pills or "<span style=\"color:#94A3B8;font-size:12px;\">Generalist role</span>"


def _meta_line(job: Dict[str, Any]) -> str:
    bits = []
    if job.get("company"):
        bits.append(f"🏢 {_e(job.get('company'))}")
    if job.get("location"):
        bits.append(f"📍 {_e(job.get('location'))}")
    if job.get("work_style"):
        bits.append(f"💼 {_e(job.get('work_style'))}")
    exp = ""
    if job.get("min_experience") is not None:
        try:
            mn = int(job.get("min_experience") or 0)
            mx = job.get("max_experience")
            exp = f"{mn}-{int(mx)} yrs" if mx else f"{mn}+ yrs"
            bits.append(f"⭐ {exp}")
        except (TypeError, ValueError):
            pass
    if not bits:
        return ""
    return f"<p style=\"margin:0 0 10px 0;color:#475569;font-size:13px;\">{' &nbsp;·&nbsp; '.join(bits)}</p>"


def render_email_text(subscriber: Dict[str, Any], matched_jobs: List[Dict[str, Any]]) -> str:
    """Plain-text fallback (deliverability + screen readers)."""
    lines = [
        f"Hello {subscriber.get('Full Name', 'there')},",
        "",
        f"Here are your top {len(matched_jobs)} personalized jobs (Fireflylabz AI Job Alerts)",
        f"as a {subscriber.get('Primary Role', '')}:",
        "",
    ]
    for i, job in enumerate(matched_jobs, 1):
        lines += [
            f"{i}. {job.get('title', '')} - {job.get('company', '')}",
            f"   Why: {job.get('match_rationale', 'Great match.')}",
            f"   Apply: {job.get('apply_url', '')}",
            "",
        ]
    lines += ["- FireflyLabz | Weekly Job Alert | Reply to update preferences"]
    link = unsubscribe_url(subscriber.get("Email Address", ""))
    if link:
        lines += [f"Unsubscribe: {link}"]
    else:
        lines += ["Reply STOP to unsubscribe."]
    return "\n".join(lines)


def _brand_header() -> str:
    """Outlook-safe header: white bar with light logo + dark-mode swap + text fallback."""
    light = (LOGO_LIGHT_URL or "").strip()
    dark = (LOGO_DARK_URL or "").strip()
    web = (BRAND_WEBSITE or "").strip() or "https://fireflylabz.example.com"
    use_light = bool(light) and "example.com" not in light
    use_dark = bool(dark) and "example.com" not in dark

    if use_light:
        logo_html = (
            f"<a href='{_e(web)}' style='text-decoration:none;'>"
            f"<img src='{_e(light)}' width='180' alt='FireflyLabz' "
            f"class='light-logo' style='display:block;border:0;max-width:180px;height:auto;' />"
        )
        if use_dark:
            logo_html += (
                f"<img src='{_e(dark)}' width='180' alt='FireflyLabz' "
                f"class='dark-logo' style='display:none;border:0;max-width:180px;height:auto;' />"
            )
        logo_html += "</a>"
    else:
        # Text fallback until you host assets (keeps preview + Outlook clean)
        logo_html = (
            f"<a href='{_e(web)}' style='text-decoration:none;color:{BRAND['navy']};'>"
            f"<span style='font-size:22px;font-weight:800;letter-spacing:-.3px;'>"
            f"<span style='color:{BRAND['navy']};'>firefly</span>"
            f"<span style='color:{BRAND['amber_dark']};'>Labz</span></span>"
            f"<span style='display:block;font-size:11px;letter-spacing:2px;color:{BRAND['muted']};'>"
            f"AI JOB ALERTS</span></a>"
        )

    return (
        "<tr><td class='header-cell' style='background:#ffffff;padding:16px 24px;"
        "border-bottom:3px solid #F59E0B;'>"
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0'>"
        "<tr>"
        f"<td align='left' valign='middle'>{logo_html}</td>"
        "<td align='right' valign='middle' class='header-date' "
        "style='font-size:12px;color:#64748B;'>Weekly Digest</td>"
        "</tr></table></td></tr>"
    )


def _banner_hero(name: str, n: int, role: str) -> str:
    banner = (BANNER_URL or "").strip()
    use_banner = bool(banner) and "example.com" not in banner
    if use_banner:
        # Wide dark gold banner you attached; hero text overlaid below for Outlook safety
        return (
            "<tr><td style='background:#0B0F1A;padding:0;'>"
            f"<img src='{_e(banner)}' width='600' alt='FireflyLabz — Connecting right talents to right teams' "
            "style='display:block;width:100%;max-width:600px;height:auto;border:0;' />"
            "</td></tr>"
            "<tr><td style='background:#0F172A;padding:20px 24px;color:#fff;'>"
            f"<h1 style='margin:0 0 8px 0;font-size:24px;line-height:1.2;color:#fff;'>"
            f"Hello {name} — Top <span style='color:#FBBF24;'>{n} {role} matches</span></h1>"
            "<p style='margin:0;color:#CBD5E1;font-size:14px;line-height:1.5;'>"
            "Ranked by AI on skills, experience &amp; location fit.</p>"
            "</td></tr>"
        )
    # Fallback gradient-style hero (no image yet)
    return (
        "<tr><td style='background:#0F172A;padding:24px;'>"
        f"<h1 style='margin:0 0 8px 0;font-size:24px;color:#fff;'>"
        f"Hello {name} — Top <span style='color:#FBBF24;'>{n} {role} matches</span></h1>"
        "<p style='margin:0;color:#CBD5E1;font-size:14px;'>"
        "Ranked by AI on skills, experience &amp; location fit.</p>"
        "</td></tr>"
    )


def _job_card(job: Dict[str, Any], idx: int) -> str:
    badge = "Top Pick" if idx == 1 else f"Match #{idx}"
    return f"""
        <tr><td style="padding:0 24px 16px 24px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                 style="border:1px solid {BRAND['card_border']};border-radius:12px;background:#ffffff;">
            <tr><td style="padding:16px 20px 4px 20px;">
              <span style="display:inline-block;background:{BRAND['navy']};color:#fff;font-size:11px;
                font-weight:700;letter-spacing:.5px;padding:4px 10px;border-radius:999px;">{badge}</span>
            </td></tr>
            <tr><td style="padding:8px 20px 0 20px;">
              <h3 style="margin:0 0 4px 0;color:#0F172A;font-size:18px;">
                {_e(job.get('title', ''))}</h3>
              {_meta_line(job)}
            </td></tr>
            <tr><td style="padding:0 20px 10px 20px;">{_skills_pills(job.get('required_skills'))}</td></tr>
            <tr><td style="padding:10px 20px;background:#EFF6FF;border-top:1px solid #DBEAFE;border-bottom:1px solid #DBEAFE;">
              <p style="margin:0;color:#1E40AF;font-size:14px;line-height:1.5;">
                <strong>Why this fits you:</strong> {_e(job.get('match_rationale', 'Great match.'))}</p>
            </td></tr>
            <tr><td style="padding:14px 20px 18px 20px;">
              <a href="{_e(job.get('apply_url', '#'))}"
                 style="display:inline-block;background:{BRAND['amber']};color:{BRAND['navy']};
                 padding:12px 28px;text-decoration:none;border-radius:8px;font-weight:800;font-size:15px;">Apply Now &rarr;</a>
            </td></tr>
          </table>
        </td></tr>"""


def _footer(to_email: str) -> str:
    link = unsubscribe_url(to_email)
    if link:
        unsub = (f"<a href='{link}' style='color:#94A3B8;text-decoration:underline;'>Unsubscribe</a>"
                 f" | <a href='{link}' style='color:#94A3B8;text-decoration:underline;'>Manage preferences</a>")
    else:
        # No UNSUBSCRIBE_BASE_URL yet: reply-based opt-out (still CAN-SPAM valid)
        unsub = "Manage preferences | Reply STOP to unsubscribe"
    return (
        "<tr><td align='center' style='padding:0 24px 24px 24px;color:#94A3B8;font-size:12px;'>"
        f"Weekly Job Alert | FireflyLabz AI | {unsub}<br>"
        "You are receiving this because you subscribed at FireflyLabz.</td></tr>"
    )


def render_email_html(subscriber: Dict[str, Any], matched_jobs: List[Dict[str, Any]]) -> str:
    name = _e(subscriber.get("Full Name", "there"))
    role = _e(subscriber.get("Primary Role", ""))
    exp = subscriber.get("_experience_years", "")
    loc = _e(subscriber.get("_location", "") or "")
    skills = subscriber.get("_skills_list") or subscriber.get("Key Skillsets", "")
    n = len(matched_jobs)
    cards = "".join(_job_card(j, i) for i, j in enumerate(matched_jobs, 1))
    chips = ""
    header = _brand_header()
    hero = _banner_hero(name, n, role)
    if exp != "":
        chips += f"<span style=\"display:inline-block;background:#E0F2FE;color:#0C4A6E;font-size:12px;font-weight:700;padding:4px 12px;border-radius:999px;margin-right:6px;\">STAR {exp} yrs</span>"
    if loc:
        chips += f"<span style=\"display:inline-block;background:#E0E7FF;color:#3730A3;font-size:12px;font-weight:700;padding:4px 12px;border-radius:999px;\">PIN {loc}</span>"
    preview = f"{name}, your top {n} personalized {role} matches are inside."
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>Top {n} job matches - FireflyLabz</title>"
        "<meta name=\"color-scheme\" content=\"light dark\">"
        "<meta name=\"supported-color-schemes\" content=\"light dark\">"
        "<style>@media (prefers-color-scheme: dark){.light-logo{display:none !important;}"
        ".dark-logo{display:block !important;}.header-cell{background:#0B0F1A !important;}"
        ".header-date{color:#CBD5E1 !important;}}</style></head>"
        f"<body style=\"margin:0;padding:0;background:{BRAND['bg']};font-family:Arial,Helvetica,sans-serif;\">"
        f"<div style=\"display:none;max-height:0;overflow:hidden;opacity:0;\">{_e(preview)}</div>"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        f"style=\"background:{BRAND['bg']};\"><tr><td align=\"center\" style=\"padding:24px 12px;\">"
        "<table role=\"presentation\" width=\"600\" cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"max-width:600px;width:100%;background:#fff;border-radius:16px;overflow:hidden;"
        f"border:1px solid {BRAND['card_border']};\">"
        f"{header}{hero}"
        f"<tr><td style=\"padding:16px 24px 0 24px;\">"
        f"<div>{chips}</div><div style=\"margin-top:10px;\">{_skills_pills(skills)}</div>"
        "</td></tr><tr><td style=\"height:16px;\"></td></tr>"
        f"{cards}"
        "<tr><td style=\"padding:6px 24px 20px 24px;\">"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
        "style=\"background:#F8FAFC;border:1px dashed #CBD5E1;border-radius:10px;\">"
        "<tr><td style=\"padding:14px 18px;color:#475569;font-size:13px;\">"
        "Not quite right? Reply with updated skills / location and next week's picks re-rank."
        "</td></tr></table></td></tr>"
        f"{_footer(subscriber.get('Email Address', ''))}"
        "</table><p style=\"color:#94A3B8;font-size:11px;\">2026 Fireflylabz, Chennai</p>"
        "</td></tr></table></body></html>"
    )


def send_newsletter_email(subscriber: Dict[str, Any], matched_jobs: List[Dict[str, Any]],
                          dry_run: bool = DRY_RUN) -> bool:
    if not matched_jobs:
        return False
    html_body = render_email_html(subscriber, matched_jobs)
    text_body = render_email_text(subscriber, matched_jobs)
    to_email = subscriber.get("Email Address", "")
    name = subscriber.get("Full Name", "there")
    subject = f"{name}, your top {len(matched_jobs)} {subscriber.get('Primary Role','')} matches are in"
    if dry_run:
        print(f"  [dry-run] would email {to_email}: {subject}")
        return True
    link = unsubscribe_url(to_email)
    # primary = EMAIL_PROVIDER, other = automatic fallback
    order = ["brevo", "resend"] if EMAIL_PROVIDER == "brevo" else ["resend", "brevo"]
    senders = {"brevo": _send_via_brevo, "resend": _send_via_resend}
    last_err = None
    for provider in order:
        for attempt in range(2):
            try:
                senders[provider](to_email, subject, html_body, text_body, link)
                if provider != order[0]:
                    print(f"  [email] sent via fallback {provider}")
                return True
            except Exception as e:  # rate-limit / transient / bad sender
                last_err = e
                print(f"  [email] {provider} attempt {attempt+1} failed: {e}")
                time.sleep(2 * (attempt + 1))
        print(f"  [email] {provider} FAILED, trying fallback...")
    print(f"  [email] FAILED after retries: {last_err}")
    return False


def preview_email(path: str = "preview_email.html") -> str:
    """Render sample template to file for browser check. Run: python -c 'from emailer import preview_email; preview_email()'"""
    demo_sub = {"Full Name": "Priya Sharma", "Primary Role": "Python Developer",
                "_experience_years": 4, "_location": "Chennai",
                "_skills_list": ["Python", "PostgreSQL", "AWS"]}
    demo_jobs = [
        {"title": "Backend Engineer (Python)", "company": "Datawise",
         "location": "Chennai", "work_style": "Hybrid",
         "min_experience": 2, "max_experience": 5,
         "required_skills": ["Python", "PostgreSQL", "AWS"],
         "apply_url": "https://example.com/jobs/be1",
         "match_rationale": "Your 4 yrs Python + Postgres + AWS maps directly to their API platform role."},
        {"title": "Senior Frontend Engineer", "company": "Acme Labs",
         "location": "Remote", "work_style": "Remote",
         "min_experience": 4, "max_experience": 8,
         "required_skills": ["React", "TypeScript"],
         "apply_url": "https://example.com/jobs/fe1",
         "match_rationale": "Strong crossover: your Python API experience pairs with their full-stack React role."},
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_email_html(demo_sub, demo_jobs))
    print(f"Preview written to {path} - open in browser.")
    return path
