# CityBot2 — Claude Code Instructions

## Tech stack
- Python async bot monitoring Ventura, CA (weather, earthquakes, news) and posting to social media
- FastAPI web dashboard (`web/app.py`)
- SQLAlchemy models in `database/models.py`

## Auto-fix guidelines
- **Test command:** `python -m py_compile $(find . -name "*.py" ! -path "./.git/*" | tr "\n" " ") && echo "Syntax OK"`
- No pytest suite — syntax check only
- Only modify the file shown in the stack trace
- Do not modify `config/cities/*.json` for code bugs
- Async/await throughout — maintain async consistency
- Env vars from `config/credentials.env.example` pattern (never hardcode)

## File map
- `main.py` — entry point
- `monitors/` — earthquake, weather, news polling
- `social_media/platforms/` — Bluesky, Twitter, Reddit, etc.
- `web/app.py` — FastAPI admin dashboard
- `database/models.py` — SQLAlchemy models