import pathlib
import subprocess
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

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
