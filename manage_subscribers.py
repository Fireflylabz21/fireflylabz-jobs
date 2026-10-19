"""CLI: unsubscribe / resubscribe / delete / list-unsubscribed.
Usage:
  python manage_subscribers.py list-unsubscribed
  python manage_subscribers.py unsubscribe user@example.com
  python manage_subscribers.py resubscribe user@example.com
  python manage_subscribers.py delete user@example.com   # GDPR only
"""
import sys
from db import get_db_connection
from unsubscribe import unsubscribe_email, resubscribe_email, delete_subscriber


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1].lower()
    conn = get_db_connection()
    try:
        if cmd == "list-unsubscribed":
            with conn.cursor() as cur:
                cur.execute("SELECT email, full_name, unsubscribed_at, notes FROM subscribers "
                            "WHERE status='Unsubscribed' ORDER BY unsubscribed_at DESC NULLS LAST;")
                rows = [dict(r) for r in cur.fetchall()]
            print(f"Unsubscribed: {len(rows)}")
            for r in rows:
                print(f"  - {r['email']} | {r.get('full_name','')} | {r.get('unsubscribed_at')} | {r.get('notes','')}")
        elif cmd in ("unsubscribe", "resubscribe", "delete") and len(sys.argv) == 3:
            email = sys.argv[2]
            fn = {"unsubscribe": unsubscribe_email, "resubscribe": resubscribe_email,
                  "delete": delete_subscriber}[cmd]
            ok = fn(conn, email)
            print(f"{cmd} {email}: {'OK' if ok else 'not found / no change'}")
        else:
            print(__doc__)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
