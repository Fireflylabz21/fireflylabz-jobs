"""Hosted one-click page ($0). Deploy free on Streamlit Community Cloud.

Setup:
  1. pip install streamlit  (add to requirements)
  2. Push repo, deploy this file on share.streamlit.io
  3. Set Secrets: SUPABASE_DB_URL, UNSUBSCRIBE_SECRET
  4. Set .env UNSUBSCRIBE_BASE_URL=https://<your-app>.streamlit.app
Users clicking footer link land here -> auto unsubscribes via ?email=&sig=
"""
import streamlit as st
from db import get_db_connection
from unsubscribe import verify_sig, unsubscribe_email

st.set_page_config(page_title="Unsubscribe — FireflyLabz", page_icon="🔥")
st.markdown("## 🔥 FireflyLabz Job Alerts")
q = st.query_params
email = (q.get("email", "") or "").strip().lower()
sig = (q.get("sig", "") or "").strip()

if not email or not sig:
    st.warning("Missing unsubscribe link. Please use the link in your email, or type your email below.")
    email = st.text_input("Email").strip().lower()
    if st.button("Unsubscribe") and email:
        conn = get_db_connection()
        ok = unsubscribe_email(conn, email, reason="manual-page")
        conn.close()
        st.success("You've been unsubscribed." if ok else "Email not found.")
elif not verify_sig(email, sig):
    st.error("Invalid link. Please use the latest email link.")
else:
    conn = get_db_connection()
    ok = unsubscribe_email(conn, email, reason="one-click")
    conn.close()
    if ok:
        st.success(f"Unsubscribed {email}. You won't receive weekly alerts anymore.")
        st.caption("Changed your mind? Reply to any old email with RESUBSCRIBE.")
    else:
        st.info("You're already unsubscribed.")
