"""Dev-environment seed (PRD section 14.3) — safe to run repeatedly (idempotent, checks first).

Usage: python -m app.db.seed
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models import ModelVersion, SystemConfig, User

DEV_USER_EMAIL = "dev@pcb-inspect.local"
DEV_USER_PASSWORD = "devpassword123"  # local dev-only seed account, not production
MODEL_VERSION = "v1.0.0"

DEFAULT_SYSTEM_CONFIG: dict[str, object] = {
    "min_confidence_store": 0.25,
    "min_confidence_report": 0.50,
    "agent_analysis_mode": "conditional",
    "agent_analysis_min_defect_count": 3,
    "agent_analysis_critical_classes": ["short"],
    "agent_analysis_min_severity": "high",
    "alert_defect_rate_threshold": 0.15,
    "alert_window_minutes": 60,
    "watch_naming_convention": "subdirectory_batch_filename_board",
    "retention_days": 730,
}


async def seed() -> None:
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        existing_user = await session.scalar(select(User).where(User.email == DEV_USER_EMAIL))
        if existing_user is None:
            session.add(
                User(
                    email=DEV_USER_EMAIL,
                    password_hash=hash_password(DEV_USER_PASSWORD),
                    full_name="Dev Operator",
                )
            )

        config_values = {
            **DEFAULT_SYSTEM_CONFIG,
            "llm.provider": settings.llm_provider,
            "llm.base_url": settings.llm_base_url,
            "llm.model": settings.llm_model,
            "llm.timeout_s": settings.llm_timeout_s,
            "watch_root_path": str(settings.watch_root),
            "watch_mode_enabled": True,
            "reports_output_dir": str(settings.app_data_dir / "reports"),
        }
        for key, value in config_values.items():
            existing_config = await session.scalar(
                select(SystemConfig).where(SystemConfig.key == key)
            )
            if existing_config is None:
                session.add(SystemConfig(key=key, value=value, is_secret=False))

        existing_model_version = await session.scalar(
            select(ModelVersion).where(ModelVersion.version == MODEL_VERSION)
        )
        if existing_model_version is None:
            session.add(
                ModelVersion(
                    version=MODEL_VERSION,
                    weights_path="/weights/best.pt",
                    is_active=True,
                    activated_at=datetime.now(UTC),
                )
            )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
