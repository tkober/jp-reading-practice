# API-only image. The Angular bundle ships in its own nginx image, which also
# reverse-proxies /api here (see frontend/nginx.conf).
#
# Build context is the repository root, not backend/ — nothing outside this
# directory is needed today, but keeping it consistent with the other stacks
# means the workflow and this file agree.

# Builds the JMdict dictionary (issue #7's word popover; see
# scripts/build_jmdict.py) in its own stage, so the final image only ever
# gets the ~49 MB SQLite it produces -- never the ~10 MB JMdict_e.gz download
# the script caches alongside it, and never a second copy of the main
# dependency set, which this script does not need (it uses only the standard
# library). This is also the one step in the whole build that needs network
# access beyond PyPI -- EDRDG's own FTP mirror.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS jmdict-builder
WORKDIR /build
COPY backend/scripts/build_jmdict.py ./scripts/build_jmdict.py
RUN python3 scripts/build_jmdict.py

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/app ./app
COPY --from=jmdict-builder /build/app/data/jmdict.sqlite ./app/data/jmdict.sqlite
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/topics ./topics

# DB_URL / DB_USER / DB_PASSWORD / DB_OWNER_USER / DB_OWNER_PASSWORD /
# OPENAI_API_KEY / KANJI_TRAINER_MCP_URL / CORS_ORIGINS are read at runtime
# (app/config.py) — pass them via `docker run --env-file` / -e.
ENV HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

# Shell form so $HOST/$PORT expand at runtime (exec'd via `sh -c`, so uvicorn
# still becomes PID 1's child and receives signals).
CMD ["sh", "-c", "exec uv run uvicorn app.main:app --host \"$HOST\" --port \"$PORT\""]
