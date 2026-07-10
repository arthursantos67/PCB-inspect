import pathlib
import subprocess
import sys
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app

BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent

_TABLES_IN_FK_ORDER = (
    "detection",
    "analysis",
    "inspection_image",
    "board",
    "batch",
    "audit_log",
    "model_version",
    "system_config",
    '"user"',
)


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema() -> None:
    """Applies the real Alembic chain once per session — constraints/triggers must be real DDL."""
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, check=True
    )


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE TABLE {', '.join(_TABLES_IN_FK_ORDER)} RESTART IDENTITY CASCADE")
        )
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An HTTP client for `app`, routed to `db_session` — the app's own module-level engine is
    bound to a different event loop than pytest-asyncio's per-test loop, so requests must be
    rebound to a session created inside the running test's loop instead.
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
