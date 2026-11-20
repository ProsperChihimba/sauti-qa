# CPU image: API, CPU/LLM worker, scheduler (beat) and inbox watcher.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
# Install dependencies first (cached layer), then the code.
RUN mkdir app && touch app/__init__.py && pip install . && rm -rf app
COPY . .
RUN pip install --no-deps . && useradd -r -u 10001 sauti && mkdir -p /data/inbox /data/storage && chown -R sauti /data
USER sauti
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
