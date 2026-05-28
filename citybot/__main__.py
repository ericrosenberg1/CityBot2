"""CityBot2 entry point.

Supports three modes via CITYBOT_MODE env var:
  all  - web UI + bot (default, single container)
  web  - web UI only
  bot  - bot only (headless)

On first run with no city configured, starts web-only and directs
the user to /setup to create an admin account and configure the city.
"""
import os
import sys
import asyncio
import logging
import signal
import threading
import time

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("CityBot2")

DIRS = ["logs", "data", "cache/weather_maps", "cache/maps", "config/cities"]
CRED_PATH = os.path.join("config", "credentials.env")


def ensure_dirs():
    for d in DIRS:
        os.makedirs(d, exist_ok=True)


def ensure_config():
    """Create a minimal credentials.env if missing so the web UI can start."""
    if not os.path.exists(CRED_PATH):
        with open(CRED_PATH, "w") as f:
            f.write("# CityBot2 — finish setup at http://localhost:8080/setup\nCITY_NAME=\n")
        logger.info("Created default config — complete setup via the web UI")


def city_is_configured() -> bool:
    """Check if a city name is set via env var or credentials file."""
    if os.getenv("CITY_NAME"):
        return True
    if os.path.exists(CRED_PATH):
        from dotenv import load_dotenv
        load_dotenv(CRED_PATH, override=False)
    return bool(os.getenv("CITY_NAME"))


def run_web():
    """Start the FastAPI web server (blocks)."""
    import uvicorn

    port = int(os.getenv("CITYBOT_PORT", "8080"))
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
        proxy_headers=True,          # trust X-Forwarded-For/Proto from Caddy/nginx
        forwarded_allow_ips="*",     # allow any proxy (Docker network)
    )


def run_bot():
    """Start the async bot loop (blocks)."""
    from main import async_main

    asyncio.run(async_main())


def run_all():
    """Start web in a daemon thread, then start the bot in the main thread.

    If no city is configured yet, only the web UI runs so the user can
    complete first-time setup.
    """
    port = os.getenv("CITYBOT_PORT", "8080")

    web_thread = threading.Thread(target=run_web, name="web", daemon=True)
    web_thread.start()
    time.sleep(0.5)

    if not city_is_configured():
        logger.info(
            "No city configured. Open http://localhost:%s/setup to get started.", port
        )
        # Block on the web thread until the user sets things up and restarts
        try:
            while web_thread.is_alive():
                web_thread.join(timeout=2)
        except KeyboardInterrupt:
            logger.info("Shutting down…")
        return

    logger.info("Starting bot for %s …", os.getenv("CITY_NAME"))
    run_bot()


def main():
    ensure_dirs()
    ensure_config()

    mode = os.getenv("CITYBOT_MODE", "all").lower()
    port = os.getenv("CITYBOT_PORT", "8080")

    logger.info("CityBot2 starting  mode=%s  port=%s", mode, port)

    if mode == "web":
        run_web()
    elif mode == "bot":
        if not city_is_configured():
            logger.error("Cannot start bot — no CITY_NAME configured.")
            sys.exit(1)
        run_bot()
    else:
        run_all()


if __name__ == "__main__":
    main()
