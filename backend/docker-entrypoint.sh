#!/usr/bin/env sh
set -e

# Migrations run on boot because the free tier has no release phase and no separate worker.
# Safe here only because there is exactly one instance; with two or more, Alembic's
# transactional DDL can still race on the version table.
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "[entrypoint] applying database migrations"
  alembic upgrade head
fi

echo "[entrypoint] starting api"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --limit-concurrency "${UVICORN_LIMIT_CONCURRENCY:-32}" \
  --timeout-keep-alive 75 \
  --no-server-header \
  --no-access-log
