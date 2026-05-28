FROM python:3.12-slim AS builder

# System deps needed to compile cartopy, matplotlib, bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgeos-dev libproj-dev proj-data proj-bin libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Production image ---
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-c1v5 libproj25 proj-data proj-bin curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r citybot && useradd -r -g citybot -d /app citybot

COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

RUN mkdir -p data logs cache/weather_maps cache/maps config/cities \
    && chown -R citybot:citybot /app

USER citybot

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CITYBOT_PORT=8080 \
    CITYBOT_MODE=all

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1

ENTRYPOINT ["python", "-m", "citybot"]
