"""DB session helper for Celery tasks.

Each task execution drives its own throwaway `asyncio.run()` loop (see `app/tasks/pipeline.py`),
unlike the FastAPI app which owns one long-lived loop. Reusing `app.db.session.AsyncSessionLocal`
(and its pooled asyncpg connections) across those short-lived loops fails — a pooled connection
opened under one loop can't be checked out again once that loop has closed.

`NullPool` sidesteps this at its root instead of working around it per call: it never holds a
connection between checkouts, so every checkout opens a fresh one appropriate for whichever loop
is currently running, and none can ever be handed back to a loop that's since closed. That makes
the engine safe to reuse across every task invocation for the life of the worker process — no
per-call engine construction/teardown needed.

It does *not*, however, make one engine object safe to reuse across OS threads. Under a
`--pool=threads` worker (e.g. `worker-agents`, issue #40), each concurrent task's `asyncio.run()`
runs on a genuinely different OS thread with its own event loop. SQLAlchemy's async engine lazily
creates internal `asyncio.Lock`s (e.g. the pool's first-connect-event mutex) bound to whichever
loop first touches them; a second thread's loop then hitting that same lock fails with
`RuntimeError: <asyncio.locks.Lock ...> is bound to a different event loop`. Keeping the engine
(and its session factory) thread-local — one built lazily per OS thread, reused for that thread's
lifetime — preserves the "build once, reuse for the life of the worker" property while keeping
each engine's internal asyncio state confined to the single OS thread that created it.
"""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_local = threading.local()


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] | None = getattr(_local, "session_factory", None)
    if factory is None:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        _local.session_factory = factory
    return factory


@asynccontextmanager
async def task_db_session() -> AsyncIterator[AsyncSession]:
    async with _get_session_factory()() as session:
        yield session
