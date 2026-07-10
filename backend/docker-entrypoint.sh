#!/bin/sh
set -e

# Only the api service runs migrations + seed, so worker/beat containers starting in parallel
# don't race each other applying the same migration.
if [ "$1" = "uvicorn" ]; then
    alembic upgrade head
    python -m app.db.seed
fi

exec "$@"
