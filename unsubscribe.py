"""One-click unsubscribe (signed, $0, no server needed for MVP).

Flow:
  Email footer -> UNSUBSCRIBE_BASE_URL/unsubscribe?email=..&sig=..
  -> Supabase Edge Function OR Streamlit/Supabase-hosted page calls unsubscribe_email()
  -> status='Unsubscribed', unsubscribed_at=NOW()

Security: HMAC-SHA256(email, UNSUBSCRIBE_SECRET). Prevents forged unsubscribes.
No delete: we soft-delete (status flag) for audit + Resend suppression + re-subscribe.
Use delete_subscriber() CLI only for GDPR right-to-erasure requests.
"""
import hashlib
import hmac
from typing import Optional

from config import UNSUBSCRIBE_BASE_URL, UNSUBSCRIBE_SECRET


def sign_email(email: str, secret: Optional[str] = None) -> str:
    key = (secret if secret is not None else UNSUBSCRIBE_SECRET or "").encode()
    return hmac.new(key, email.strip().lower().encode(), hashlib.sha256).hexdigest()[:32]


def unsubscribe_url(email: str) -> str:
    """Return full one-click URL, or '' if UNSUBSCRIBE_BASE_URL not configured."""
    base = (UNSUBSCRIBE_BASE_URL or "").rstrip("/")
    if not base:
        return ""
    em = email.strip().lower()
    return f"{base}/unsubscribe?email={em}&sig={sign_email(em)}"


def verify_sig(email: str, sig: str, secret: Optional[str] = None) -> bool:
    return hmac.compare_digest(sign_email(email, secret), (sig or "").strip().lower())


def unsubscribe_email(conn, email: str, reason: str = "one-click") -> bool:
    """Soft-delete: status -> 'Unsubscribed'. Returns True if row changed."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE subscribers SET status='Unsubscribed', notes=%s "
            "WHERE lower(email)=lower(%s) AND COALESCE(status,'Active') <> 'Unsubscribed';",
            (f"Unsubscribed via {reason[:80]}", email.strip()),
        )
        changed = cur.rowcount > 0
    conn.commit()
    return changed


def resubscribe_email(conn, email: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE subscribers SET status='Active', notes='Resubscribed' "
            "WHERE lower(email)=lower(%s);",
            (email.strip(),),
        )
        changed = cur.rowcount > 0
    conn.commit()
    return changed


def delete_subscriber(conn, email: str) -> bool:
    """Hard delete (GDPR). Prefer unsubscribe_email for normal opt-outs."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM subscribers WHERE lower(email)=lower(%s);", (email.strip(),))
        changed = cur.rowcount > 0
    conn.commit()
    return changed
