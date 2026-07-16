"""GET /api/v1/inspections (FR-07, PRD section 11.3) — filter combinations, pagination
boundaries, and ordering.

Detections/analyses are constructed directly against the ORM rather than through the full
ingestion+inference pipeline (covered elsewhere: tests/test_ingestion.py,
tests/test_pipeline_tasks.py) — this file is only concerned with the listing query itself.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    Batch,
    Board,
    BoardDisposition,
    Detection,
    InspectionImage,
    ModelVersion,
    User,
)
from app.models.enums import (
    AnalysisReviewStatus,
    AnalysisSource,
    AnalysisStatus,
    BoardDispositionDecision,
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

_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_account(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/setup", json=ACCOUNT)
    return response.json()["access_token"]


async def _make_model_version(db: AsyncSession) -> ModelVersion:
    model_version = ModelVersion(version="v1.0.0", weights_path="/weights/best.pt", is_active=True)
    db.add(model_version)
    await db.flush()
    return model_version


async def _make_board(db: AsyncSession, batch_number: str, board_number: str) -> Board:
    batch = await db.scalar(select(Batch).where(Batch.batch_number == batch_number))
    if batch is None:
        batch = Batch(batch_number=batch_number)
        db.add(batch)
        await db.flush()
    board = Board(batch_id=batch.id, board_number=board_number)
    db.add(board)
    await db.flush()
    return board


async def _make_image(
    db: AsyncSession,
    board: Board | None,
    *,
    status: ImageStatus = ImageStatus.COMPLETED,
    created_at: datetime,
    failure_reason: str | None = None,
) -> InspectionImage:
    image = InspectionImage(
        board_id=board.id if board is not None else None,
        source=ImageSource.WATCH_FOLDER,
        original_path=f"/tmp/{uuid.uuid4()}.jpg",
        checksum_sha256=uuid.uuid4().hex,
        status=status,
        failure_reason=failure_reason,
        created_at=created_at,
    )
    db.add(image)
    await db.flush()
    return image


async def _make_detection(
    db: AsyncSession,
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
    db.add(detection)
    await db.flush()
    return detection


async def _make_analysis(
    db: AsyncSession,
    image: InspectionImage,
    severity: Severity,
    *,
    review_status: AnalysisReviewStatus = AnalysisReviewStatus.PENDING,
) -> Analysis:
    analysis = Analysis(
        image_id=image.id,
        status=AnalysisStatus.COMPLETED,
        source=AnalysisSource.KNOWLEDGE_BASE,
        severity_max=severity,
        review_status=review_status,
    )
    db.add(analysis)
    await db.flush()
    return analysis


@pytest.fixture
async def seeded(db_session: AsyncSession) -> dict[str, InspectionImage]:
    """A small, deliberately varied fixture (2 batches, 3 boards, mixed statuses/severities/
    defect types, distinct creation timestamps) reused across every filter/pagination/
    ordering assertion below.
    """
    model_version = await _make_model_version(db_session)

    board_a1 = await _make_board(db_session, "BATCH-A", "A1")
    board_a2 = await _make_board(db_session, "BATCH-A", "A2")
    board_b1 = await _make_board(db_session, "BATCH-B", "B1")

    img1 = await _make_image(db_session, board_a1, created_at=_NOW - timedelta(days=3))
    await _make_detection(db_session, img1, model_version, DefectType.MOUSE_BITE)
    await _make_analysis(db_session, img1, Severity.LOW)

    img2 = await _make_image(db_session, board_a2, created_at=_NOW - timedelta(days=2))
    await _make_detection(db_session, img2, model_version, DefectType.SHORT)
    await _make_analysis(db_session, img2, Severity.CRITICAL)

    img3 = await _make_image(db_session, board_b1, created_at=_NOW - timedelta(days=1))
    await _make_detection(db_session, img3, model_version, DefectType.MOUSE_BITE)
    await _make_detection(db_session, img3, model_version, DefectType.SHORT)
    await _make_analysis(db_session, img3, Severity.HIGH)

    img4 = await _make_image(
        db_session,
        board_b1,
        status=ImageStatus.FAILED,
        created_at=_NOW,
        failure_reason="corrupt file",
    )

    img5 = await _make_image(db_session, board_a1, status=ImageStatus.QUEUED, created_at=_NOW)

    await db_session.commit()
    return {"img1": img1, "img2": img2, "img3": img3, "img4": img4, "img5": img5}


async def _list(client: AsyncClient, token: str, **params: object) -> dict:
    response = await client.get(
        "/api/v1/inspections", params=params, headers=_auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _ids(body: dict) -> list[str]:
    return [row["id"] for row in body["results"]]


# --- Response shape / auth --------------------------------------------------------------------


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/inspections")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_returns_documented_pagination_envelope(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token)
    assert set(body.keys()) == {"count", "next", "previous", "results"}
    assert body["count"] == 5
    assert body["previous"] is None
    row = body["results"][0]
    assert set(row.keys()) == {
        "id",
        "status",
        "batch_number",
        "board_number",
        "defect_types",
        "severity_max",
        "review_status",
        "disposition_recommendation",
        "disposition",
        "failure_reason",
        "created_at",
        "processed_at",
    }


# --- Filters: alone --------------------------------------------------------------------------


async def test_filter_by_defect_type(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, defect_type="short")
    assert set(_ids(body)) == {str(seeded["img2"].id), str(seeded["img3"].id)}


async def test_filter_by_multiple_defect_types_is_union(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    response = await client.get(
        "/api/v1/inspections",
        params=[("defect_type", "short"), ("defect_type", "mouse_bite")],
        headers=_auth_headers(token),
    )
    assert response.status_code == 200
    assert set(_ids(response.json())) == {
        str(seeded["img1"].id),
        str(seeded["img2"].id),
        str(seeded["img3"].id),
    }


async def test_filter_by_batch_number(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, batch_number="BATCH-A")
    assert set(_ids(body)) == {
        str(seeded["img1"].id),
        str(seeded["img2"].id),
        str(seeded["img5"].id),
    }


async def test_filter_by_board_number(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, board_number="B1")
    assert set(_ids(body)) == {str(seeded["img3"].id), str(seeded["img4"].id)}


async def test_filter_by_status(client: AsyncClient, seeded: dict[str, InspectionImage]) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, status="FAILED")
    assert _ids(body) == [str(seeded["img4"].id)]
    assert body["results"][0]["failure_reason"] == "corrupt file"


async def test_filter_by_severity(client: AsyncClient, seeded: dict[str, InspectionImage]) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, severity="critical")
    assert _ids(body) == [str(seeded["img2"].id)]


async def test_filter_by_date_range(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(
        client,
        token,
        date_from=(_NOW - timedelta(days=2)).isoformat(),
        date_to=(_NOW - timedelta(days=1)).isoformat(),
    )
    assert set(_ids(body)) == {str(seeded["img2"].id), str(seeded["img3"].id)}


async def test_filter_with_no_matches_returns_empty_results(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, batch_number="BATCH-DOES-NOT-EXIST")
    assert body == {"count": 0, "next": None, "previous": None, "results": []}


# --- Filters: review_status / disposition (FR-10, Issue 33) --------------------------------


async def test_filter_by_review_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_account(client)
    board = await _make_board(db_session, "BATCH-A", "A1")

    validated_img = await _make_image(db_session, board, created_at=_NOW)
    await _make_analysis(
        db_session, validated_img, Severity.LOW, review_status=AnalysisReviewStatus.VALIDATED
    )

    rejected_img = await _make_image(db_session, board, created_at=_NOW)
    await _make_analysis(
        db_session, rejected_img, Severity.LOW, review_status=AnalysisReviewStatus.REJECTED
    )

    pending_img = await _make_image(db_session, board, created_at=_NOW)
    await _make_analysis(db_session, pending_img, Severity.LOW)

    await db_session.commit()

    body = await _list(client, token, review_status="VALIDATED")
    assert _ids(body) == [str(validated_img.id)]

    body = await _list(client, token, review_status="REJECTED")
    assert _ids(body) == [str(rejected_img.id)]


async def test_filter_by_disposition(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _setup_account(client)
    user = await db_session.scalar(select(User).where(User.email == ACCOUNT["email"]))
    assert user is not None
    board = await _make_board(db_session, "BATCH-A", "A1")

    approved_img = await _make_image(db_session, board, created_at=_NOW)
    db_session.add(
        BoardDisposition(
            image_id=approved_img.id,
            decision=BoardDispositionDecision.APPROVED,
            decided_by=user.id,
        )
    )

    discarded_img = await _make_image(db_session, board, created_at=_NOW)
    db_session.add(
        BoardDisposition(
            image_id=discarded_img.id,
            decision=BoardDispositionDecision.DISCARDED,
            decided_by=user.id,
        )
    )

    no_disposition_img = await _make_image(db_session, board, created_at=_NOW)

    await db_session.commit()

    body = await _list(client, token, disposition="approved")
    assert _ids(body) == [str(approved_img.id)]

    body = await _list(client, token, disposition="discarded")
    assert _ids(body) == [str(discarded_img.id)]

    approved_again = await _list(client, token, disposition="approved")
    assert str(no_disposition_img.id) not in _ids(approved_again)


# --- Filters: combined ------------------------------------------------------------------------


async def test_combined_batch_and_defect_type_filters(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, batch_number="BATCH-A", defect_type="short")
    assert _ids(body) == [str(seeded["img2"].id)]


async def test_combined_status_and_board_filters_narrow_to_zero(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, board_number="A1", status="FAILED")
    assert body["count"] == 0


# --- Ordering ----------------------------------------------------------------------------------


async def test_default_ordering_is_created_at_descending(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token)
    ids = _ids(body)
    # img4/img5 share `_NOW` — the `id` tiebreaker makes their relative order stable across
    # requests, but not predictable from a fresh `uuid4()`, so only the pair is asserted here.
    assert set(ids[:2]) == {str(seeded["img4"].id), str(seeded["img5"].id)}
    assert ids[2:] == [str(seeded["img3"].id), str(seeded["img2"].id), str(seeded["img1"].id)]


async def test_ordering_by_severity_descending_puts_most_critical_first(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, ordering="-severity")
    # img4/img5 have no analysis (rank -1); img1 is LOW (rank 0) < img3 HIGH < img2 CRITICAL.
    assert _ids(body)[0] == str(seeded["img2"].id)
    assert _ids(body)[1] == str(seeded["img3"].id)
    assert _ids(body)[2] == str(seeded["img1"].id)


async def test_rejects_unknown_ordering_value(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    response = await client.get(
        "/api/v1/inspections", params={"ordering": "bogus"}, headers=_auth_headers(token)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


# --- Pagination boundaries ----------------------------------------------------------------------


async def test_pagination_first_page_has_next_no_previous(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, page=1, page_size=2)
    assert body["count"] == 5
    assert len(body["results"]) == 2
    assert body["previous"] is None
    assert body["next"] is not None
    assert "page=2" in body["next"]


async def test_pagination_last_page_is_partial_with_no_next(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, page=3, page_size=2)
    assert len(body["results"]) == 1
    assert body["next"] is None
    assert body["previous"] is not None
    assert "page=2" in body["previous"]


async def test_pagination_page_beyond_last_is_empty(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    body = await _list(client, token, page=4, page_size=2)
    assert body["count"] == 5
    assert body["results"] == []
    assert body["next"] is None
    assert body["previous"] is not None


async def test_page_size_above_max_is_rejected(
    client: AsyncClient, seeded: dict[str, InspectionImage]
) -> None:
    token = await _setup_account(client)
    response = await client.get(
        "/api/v1/inspections", params={"page_size": 101}, headers=_auth_headers(token)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
