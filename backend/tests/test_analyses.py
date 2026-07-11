"""Baseline analysis generation (FR-06's baseline tier, Issue 7): source tagging, per-defect
content sourced from the knowledge base for each of the 6 defect classes, `severity_max`
computation, the `DETECTED -> COMPLETED` transition, and the `GET /api/v1/analyses/{id}` API
shape (section 11.5).

The no-defect path (no `Analysis` row at all) and end-to-end wiring through the pipeline
task are covered in `tests/test_pipeline_tasks.py`, alongside `create_baseline_analysis`.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses.service import create_baseline_analysis
from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE
from app.models import Detection, InspectionImage, ModelVersion
from app.models.enums import (
    AnalysisSource,
    AnalysisStatus,
    DefectType,
    ImageSource,
    ImageStatus,
    Severity,
)

ACCOUNT = {
    "email": "operator@pcb-inspect.local",
    "password": "correct-horse-battery",
    "full_name": "Operator",
}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_account(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/setup", json=ACCOUNT)
    return response.json()["access_token"]


async def _make_model_version(db_session: AsyncSession) -> ModelVersion:
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db_session.add(model_version)
    await db_session.flush()
    return model_version


async def _make_detected_image(db_session: AsyncSession) -> InspectionImage:
    image = InspectionImage(
        source=ImageSource.WATCH_FOLDER,
        original_path="/tmp/board.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=ImageStatus.DETECTED,
    )
    db_session.add(image)
    await db_session.flush()
    return image


async def _make_detection(
    db_session: AsyncSession,
    image: InspectionImage,
    model_version: ModelVersion,
    defect_type: DefectType,
) -> Detection:
    detection = Detection(
        image_id=image.id,
        defect_type=defect_type,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900"),
        is_reported=True,
        model_version_id=model_version.id,
    )
    db_session.add(detection)
    await db_session.flush()
    return detection


# --- Content accuracy per class (Acceptance Criteria: Content Accuracy, Correct Source Tag) --


@pytest.mark.parametrize("defect_type", list(DefectType))
async def test_baseline_analysis_matches_knowledge_base_for_every_class(
    db_session: AsyncSession, defect_type: DefectType
) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_detected_image(db_session)
    detection = await _make_detection(db_session, image, model_version, defect_type)

    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.flush()

    entry = DEFECT_KNOWLEDGE_BASE[defect_type]
    assert analysis.source == AnalysisSource.KNOWLEDGE_BASE
    assert analysis.status == AnalysisStatus.COMPLETED
    assert analysis.severity_max == entry.severity
    assert analysis.per_defect == [
        {
            "detection_id": str(detection.id),
            "description": entry.description,
            "probable_causes": list(entry.probable_causes),
            "suggested_solutions": list(entry.suggested_solutions),
            "severity": entry.severity.value,
        }
    ]
    # Instant availability (NFR-01) / no ANALYZING stopover for baseline-only (FR-06/FR-04).
    assert image.status == ImageStatus.COMPLETED


async def test_severity_max_is_the_highest_among_detected_classes(
    db_session: AsyncSession,
) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_detected_image(db_session)
    low_severity = await _make_detection(db_session, image, model_version, DefectType.SPUR)
    critical_severity = await _make_detection(db_session, image, model_version, DefectType.SHORT)

    analysis = await create_baseline_analysis(
        db_session, image, [low_severity, critical_severity]
    )

    assert analysis.severity_max == Severity.CRITICAL
    assert analysis.per_defect is not None
    assert len(analysis.per_defect) == 2


# --- API shape (Acceptance Criteria: API Shape, section 11.5) ---------------------------------


async def test_get_analysis_returns_documented_shape(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    model_version = await _make_model_version(db_session)
    image = await _make_detected_image(db_session)
    detection = await _make_detection(db_session, image, model_version, DefectType.MOUSE_BITE)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    response = await client.get(
        f"/api/v1/analyses/{analysis.id}", headers=_auth_headers(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["source"] == "knowledge_base"
    assert body["severity_max"] == DEFECT_KNOWLEDGE_BASE[DefectType.MOUSE_BITE].severity.value
    assert body["disposition_recommendation"] is None
    assert body["executive_summary"] is None
    assert body["review_status"] == "PENDING"
    assert body["per_defect"] == [
        {
            "detection_id": str(detection.id),
            "description": DEFECT_KNOWLEDGE_BASE[DefectType.MOUSE_BITE].description,
            "probable_causes": list(
                DEFECT_KNOWLEDGE_BASE[DefectType.MOUSE_BITE].probable_causes
            ),
            "suggested_solutions": list(
                DEFECT_KNOWLEDGE_BASE[DefectType.MOUSE_BITE].suggested_solutions
            ),
            "severity": DEFECT_KNOWLEDGE_BASE[DefectType.MOUSE_BITE].severity.value,
        }
    ]


async def test_get_analysis_returns_404_for_unknown_id(client: AsyncClient) -> None:
    token = await _setup_account(client)

    response = await client.get(
        f"/api/v1/analyses/{uuid.uuid4()}", headers=_auth_headers(token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_get_analysis_requires_authentication(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    model_version = await _make_model_version(db_session)
    image = await _make_detected_image(db_session)
    detection = await _make_detection(db_session, image, model_version, DefectType.SHORT)
    analysis = await create_baseline_analysis(db_session, image, [detection])
    await db_session.commit()

    response = await client.get(f"/api/v1/analyses/{analysis.id}")

    assert response.status_code == 401
