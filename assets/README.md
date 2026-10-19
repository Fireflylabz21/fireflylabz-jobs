Place your 3 attached images here:

1. `logo-light.png` = first image (navy FL + firefly on white/light)
2. `logo-dark.png` = third image (gold FL on black)
3. `banner-dark.png` = second wide image (gold banner, "A digital Startup")

Then host them (email <img> MUST be public https:// — local files are blocked):

Option A — Supabase Storage (recommended, stays $0):
  1. Supabase Dashboard -> Storage -> New bucket `assets`, Public = ON
  2. Upload these 3 files
  3. Copy each Public URL -> paste into `.env`:
     LOGO_LIGHT_URL=...
     LOGO_DARK_URL=...
     BANNER_URL=...
  4. Re-run `python -c "from emailer import preview_email; preview_email()"`

Option B — GitHub raw:
  1. Commit this folder, push
  2. Use https://raw.githubusercontent.com/<you>/<repo>/main/assets/logo-light.png etc.

Why two logos? `emailer.py` shows light logo by default, auto-swaps to
gold-on-black via `@media (prefers-color-scheme: dark)` in Apple Mail / Gmail app.
Outlook (no dark-media support) always sees the clean white header + light logo.
