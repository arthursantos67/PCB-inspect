"""DB session helper for Celery tasks.

Each task execution drives its own throwaway `asyncio.run()` loop (see `app/tasks/pipeline.py`),
unlike the FastAPI app which owns one long-lived loop. Reusing `app.db.session.AsyncSessionLocal`
(and its pooled asyncpg connections) across those short-lived loops fails — a pooled connection
opened under one loop can't be checked out again once that loop has closed.

`NullPool` sidesteps this at its root instead of working around it per call: it never holds a
connection between checkouts, so every checkout opens a fresh one appropriate for whichever loop
is currently running, and none can ever be handed back to a loop that's since closed. That makes
the engine itself safe to build once, at import time, and reuse across every task invocation for
the life of the worker process — no per-call engine construction/teardown needed.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


@asynccontextmanager
async def task_db_session() -> AsyncIterator[AsyncSession]:
    async with _session_factory() as session:
        yield session
