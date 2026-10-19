"""Diagnose SUPABASE_DB_URL without leaking password. Run: python db_check.py"""
import os
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv
load_dotenv()
url = os.getenv("SUPABASE_DB_URL","")
print(f"SUPABASE_URL={os.getenv('SUPABASE_URL','')}")
if not url:
    print("MISSING SUPABASE_DB_URL"); raise SystemExit(1)
# mask password for display
safe = url.replace(url.split("@")[0].split(":")[-1], "***") if "@" in url else "***"
print(f"DB_URL(masked)={safe}")
try:
    p = urlparse(url)
    print(f"scheme={p.scheme} user={p.username} host={p.hostname} port={p.port} db={p.path}")
    if p.username and "." in p.username:
        user_proj = p.username.split(".",1)[1]
        print(f"user project_ref={user_proj}")
    if "<DB-PASSWORD>" in url or "[YOUR-PASSWORD]" in url:
        print("ERROR: placeholder password still present - replace with real DB password")
        print("  Supabase Dashboard > Project Settings > Database > Database password > Reset > copy")
        print("  Then edit .env line SUPABASE_DB_URL, replace <DB-PASSWORD> only, save (Ctrl+S).")
        print("  Do NOT run sync/seed/main until 'DB CONNECT OK'. Waiting 10 min if ECIRCUITBREAKER.")
    elif p.hostname and "pooler.supabase.com" in p.hostname:
        print(f"pooler host={p.hostname} (must match Dashboard > Database > Connection String > Pooler)")
        if p.port == 6543:
            print("port 6543 = Transaction mode (ok for psycopg2 short scripts)")
        elif p.port == 5432:
            print("port 5432 = Session mode")
    # live test with short timeout
    import psycopg2
    c = psycopg2.connect(url, connect_timeout=10)
    cur = c.cursor(); cur.execute("select 1;"); print("DB CONNECT OK:", cur.fetchone())
    c.close()
except Exception as e:
    print(f"DB FAIL: {type(e).__name__}: {e}")
