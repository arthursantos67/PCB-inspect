"""DB session helper for Celery tasks.

Each task execution drives its own throwaway `asyncio.run()` loop (see `app/tasks/pipeline.py`),
unlike the FastAPI app which owns one long-lived loop. Reusing `app.db.session.AsyncSessionLocal`
(and its pooled asyncpg connections) across those short-lived loops fails — a pooled connection
opened under one loop can't be checked out again once that loop has closed. So tasks get their
own engine, opened and disposed within the same `asyncio.run()` call that uses it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@asynccontextmanager
async def task_db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
