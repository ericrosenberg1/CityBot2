# CityBot2 — Claude Code Instructions

## Tech stack
- Python async bot monitoring Ventura, CA (weather, earthquakes, news) and posting to social media
- FastAPI web dashboard (`web/app.py`)
- SQLAlchemy models in `database/models.py`

## Auto-fix guidelines
- **Test command:** `scripts/ci-gates.sh` (ruff on changed files, py_compile, then pytest)
- Tests live in `tests/` and run against a temp database and secret key, never `data/`. Install with `pip install -r requirements-dev.txt`, or point `CITYBOT_PYTHON` at a venv that has it
- Only modify the file shown in the stack trace
- Do not modify `config/cities/*.json` for code bugs
- Async/await throughout — maintain async consistency
- Env vars from `config/credentials.env.example` pattern (never hardcode)

## File map
- `main.py`: bot loop (`python -m citybot` is the entry point)
- `config/__init__.py`: `ConfigurationManager` (a `config.py` beside the `config/` package is never imported, which broke startup until 2026-10-20)
- `monitors/` — earthquake, weather, news polling
- `social_media/platforms/`: Bluesky, Twitter, Reddit, etc. Meta Graph helpers live in `base.py`
- `posting/queue_manager.py`: post queue: dedupe, schedule, quiet hours (city time), PostHistory
- `web/app.py` — FastAPI admin dashboard
- `database/models.py` — SQLAlchemy models