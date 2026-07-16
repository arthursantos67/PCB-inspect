import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    AuditLog,
    BoardDisposition,
    Detection,
    InspectionImage,
    ModelVersion,
    User,
)
from app.models.enums import (
    AnalysisSource,
    BoardDispositionDecision,
    DefectType,
    DetectionSource,
    ImageSource,
    ImageStatus,
)


async def _make_model_version(db_session: AsyncSession, version: str = "v1.0.0") -> ModelVersion:
    model_version = ModelVersion(version=version, weights_path="/weights/best.pt")
    db_session.add(model_version)
    await db_session.flush()
    return model_version


async def _make_image(db_session: AsyncSession) -> InspectionImage:
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path="/data/watch-root/board1.jpg",
        checksum_sha256="a" * 64,
        width=640,
        height=640,
        status=ImageStatus.QUEUED,
    )
    db_session.add(image)
    await db_session.flush()
    return image


@pytest.mark.asyncio
async def test_confidence_out_of_range_rejected(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session)
    db_session.add(
        Detection(
            image_id=image.id,
            defect_type=DefectType.SHORT,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5},
            confidence=Decimal("1.5"),
            model_version_id=model_version.id,
        )
    )
    with pytest.raises(IntegrityError, match="confidence_range"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_malformed_bbox_rejected(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session)
    db_session.add(
        Detection(
            image_id=image.id,
            defect_type=DefectType.SHORT,
            bbox={"x1": 0.6, "y1": 0.1, "x2": 0.5, "y2": 0.5},  # x1 >= x2
            confidence=Decimal("0.9"),
            model_version_id=model_version.id,
        )
    )
    with pytest.raises(IntegrityError, match="bbox_normalized_and_ordered"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_valid_detection_accepted(db_session: AsyncSession) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_image(db_session)
    db_session.add(
        Detection(
            image_id=image.id,
            defect_type=DefectType.SHORT,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5},
            confidence=Decimal("0.9"),
            is_reported=True,
            model_version_id=model_version.id,
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_second_active_model_version_rejected(db_session: AsyncSession) -> None:
    db_session.add(
        ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    )
    await db_session.flush()

    db_session.add(
        ModelVersion(version="v2.0.0", weights_path="/weights/best.pt", is_active=True)
    )
    with pytest.raises(IntegrityError, match="ix_model_version_single_active"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_reactivating_after_deactivation_is_allowed(db_session: AsyncSession) -> None:
    first = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db_session.add(first)
    await db_session.flush()

    first.is_active = False
    await db_session.flush()

    db_session.add(
        ModelVersion(version="v2.0.0", weights_path="/weights/best.pt", is_active=True)
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_manual_detection_without_model_version_accepted(db_session: AsyncSession) -> None:
    """FR-10/Issue 33: a manually-drawn detection has no producing model version at all."""
    image = await _make_image(db_session)
    db_session.add(
        Detection(
            image_id=image.id,
            defect_type=DefectType.SHORT,
            bbox={"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5},
            confidence=Decimal("1.000"),
            is_reported=True,
            model_version_id=None,
            source=DetectionSource.MANUAL,
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_board_disposition_is_unique_per_image(db_session: AsyncSession) -> None:
    image = await _make_image(db_session)
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@pcb-inspect.local", password_hash="h", full_name="Op"
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        BoardDisposition(
            image_id=image.id, decision=BoardDispositionDecision.APPROVED, decided_by=user.id
        )
    )
    await db_session.flush()

    db_session.add(
        BoardDisposition(
            image_id=image.id, decision=BoardDispositionDecision.REWORK, decided_by=user.id
        )
    )
    with pytest.raises(IntegrityError, match="uq_board_disposition_image_id"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_analysis_is_unique_per_image(db_session: AsyncSession) -> None:
    image = await _make_image(db_session)
    db_session.add(Analysis(image_id=image.id, source=AnalysisSource.KNOWLEDGE_BASE))
    await db_session.flush()

    db_session.add(Analysis(image_id=image.id, source=AnalysisSource.KNOWLEDGE_BASE))
    with pytest.raises(IntegrityError, match="uq_analysis_image_id"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_audit_log_update_rejected(db_session: AsyncSession) -> None:
    entry = AuditLog(action="config.updated", entity_type="system_config", entity_id=None)
    db_session.add(entry)
    await db_session.flush()

    entry.action = "config.changed"
    with pytest.raises(IntegrityError, match="append-only"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_audit_log_delete_rejected(db_session: AsyncSession) -> None:
    entry = AuditLog(action="config.updated", entity_type="system_config", entity_id=None)
    db_session.add(entry)
    await db_session.flush()
    await db_session.commit()

    await db_session.delete(entry)
    with pytest.raises(IntegrityError, match="append-only"):
        await db_session.flush()


@pytest.mark.asyncio
async def test_audit_log_insert_is_allowed(db_session: AsyncSession) -> None:
    db_session.add(
        AuditLog(
            action="account.created",
            entity_type="user",
            entity_id=None,
            payload={"email": "dev@pcb-inspect.local"},
            created_at=datetime.now(UTC),
        )
    )
    await db_session.flush()
