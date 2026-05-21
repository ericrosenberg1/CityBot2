# Sentry — CityBot2

Project: `rosenberg-digital/citybot2` · platform `python`

Initialised at the top of `main.py` before any other module imports, so
errors during import are captured. Uses `AsyncioIntegration` (async-aware)
and `LoggingIntegration` so `logger.error(...)` calls become Sentry events.

`pip install -r requirements.txt` will pull in `sentry-sdk>=2.18`.

Override via env: `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE`,
`SENTRY_PROFILES_SAMPLE_RATE`, `APP_ENV`, `SENTRY_RELEASE`.
