# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Builder: resolve the lockfile into a virtualenv.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies are installed from the lockfile alone, so this layer is reused until
# pyproject.toml or uv.lock actually changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev


# ---------------------------------------------------------------------------
# Runtime: no build toolchain, no compiler, no pip cache.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser docker-entrypoint.sh ./

RUN chmod +x docker-entrypoint.sh

USER appuser

EXPOSE 8000

# A free Render instance gets 512 MB and well under one CPU. One worker, a bounded number of
# concurrent requests, and no reliance on multiprocessing keep peak RSS predictable.
CMD ["./docker-entrypoint.sh"]
