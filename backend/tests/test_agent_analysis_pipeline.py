"""Wiring the agent chain into the pipeline (FR-06's agents tier, issue #31): the
`agent_analysis_mode` policy evaluated right after the baseline analysis, the handoff from
`run_inference` to `run_agent_analysis` via the `ANALYZING` status, and the fallback-to-
baseline path when the LLM is unreachable or the Reviewer loop is exhausted.

Tasks are exercised via `.apply()` (no Redis broker in the test environment, mirroring
`tests/test_pipeline_tasks.py`); the enqueue call from `run_inference` to `run_agent_analysis`
is stubbed the same way `tests/test_ingestion.py` stubs `run_inference` itself, so these tests
never need a real broker either.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select

from app.agents.errors import AgentChainAbortedError
from app.core.config import get_settings
from app.inference.detect import RawDetection
from app.models import Analysis, Detection, InspectionImage, ModelVersion, SystemConfig
from app.models.enums import (
    AnalysisSource,
    AnalysisStatus,
    DefectType,
    DispositionRecommendation,
    ImageStatus,
    Severity,
)
from app.tasks import pipeline as pipeline_module
from app.tasks.db import task_db_session
from app.tasks.pipeline import run_agent_analysis, run_inference


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class _FakeAgentAnalysisTask:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def delay(self, inspection_image_id: str) -> None:
        self.calls.append(inspection_image_id)


@pytest.fixture(autouse=True)
def _stub_agent_enqueue(monkeypatch: pytest.MonkeyPatch) -> _FakeAgentAnalysisTask:
    """No Redis broker here — `run_inference` enqueues `run_agent_analysis` via `.delay()`,
    which is stubbed the same way `tests/test_ingestion.py` stubs `run_inference`'s own
    enqueue call. Tests that exercise `run_agent_analysis` itself call `.apply()` on the real
    task directly, bypassing this stub entirely.
    """
    stub = _FakeAgentAnalysisTask()
    monkeypatch.setattr(pipeline_module, "run_agent_analysis", stub)
    return stub


async def _seed_active_model_version(version: str = "v1.0.0") -> uuid.UUID:
    async with task_db_session() as db:
        model_version = ModelVersion(
            version=version, weights_path="/weights/best.pt", is_active=True
        )
        db.add(model_version)
        await db.commit()
        return model_version.id


async def _create_image(
    *, original_path: str = "/tmp/board.jpg", status: ImageStatus = ImageStatus.QUEUED
) -> uuid.UUID:
    async with task_db_session() as db:
        image = InspectionImage(
            source="watch_folder",
            original_path=original_path,
            checksum_sha256=uuid.uuid4().hex,
            status=status,
        )
        db.add(image)
        await db.commit()
        return image.id


async def _get_image(image_id: uuid.UUID) -> InspectionImage | None:
    async with task_db_session() as db:
        return await db.get(InspectionImage, image_id)


async def _get_analysis(image_id: uuid.UUID) -> Analysis | None:
    async with task_db_session() as db:
        return await db.scalar(select(Analysis).where(Analysis.image_id == image_id))


async def _set_config(key: str, value: object) -> None:
    async with task_db_session() as db:
        db.add(SystemConfig(key=key, value=value))
        await db.commit()


class _FakeYOLO:
    def __init__(self, weights_path: str) -> None:
        pass

    def to(self, device: str) -> "_FakeYOLO":
        return self


def _stub_inference(monkeypatch: pytest.MonkeyPatch, detections: list[RawDetection]) -> None:
    monkeypatch.setattr("app.inference.model._yolo_class", lambda: _FakeYOLO)
    monkeypatch.setattr("app.inference.service.detect", lambda *args, **kwargs: detections)


def teardown_function() -> None:
    async def _truncate() -> None:
        async with task_db_session() as db:
            from sqlalchemy import text

            await db.execute(text("TRUNCATE TABLE inspection_image RESTART IDENTITY CASCADE"))
            await db.execute(text("TRUNCATE TABLE model_version RESTART IDENTITY CASCADE"))
            await db.execute(text("TRUNCATE TABLE system_config RESTART IDENTITY CASCADE"))
            await db.commit()

    _run(_truncate())


_BBOX = {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.5}


def _seed_image_and_run_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, detections: list[RawDetection]
) -> uuid.UUID:
    _stub_inference(monkeypatch, detections=detections)
    _run(_seed_active_model_version())
    monkeypatch.setattr(
        "app.tasks.pipeline.get_settings",
        lambda: get_settings().model_copy(update={"app_data_dir": tmp_path}),
    )
    image_path = tmp_path / "board.jpg"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(image_path, format="JPEG")
    image_id = _run(_create_image(original_path=str(image_path)))
    run_inference.apply(args=[str(image_id)])
    return image_id


# --- Policy Honored: conditional mode's three trigger conditions -------------------------------


def test_conditional_mode_triggers_on_defect_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    """Default `agent_analysis_min_defect_count` is 3 (matches `app/db/seed.py`) — 3
    reportable, non-critical, low-severity detections meet the count condition alone.
    """
    detections = [
        RawDetection(defect_type="spur", confidence=0.9, bbox=_BBOX) for _ in range(3)
    ]
    image_id = _seed_image_and_run_inference(tmp_path, monkeypatch, detections)

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.ANALYZING
    assert _stub_agent_enqueue.calls == [str(image_id)]

    analysis = _run(_get_analysis(image_id))
    assert analysis is not None
    assert analysis.source == AnalysisSource.KNOWLEDGE_BASE  # not yet enriched


def test_conditional_mode_triggers_on_critical_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    """Default `agent_analysis_critical_classes` is `["short"]` — a single short detection
    triggers even though it's well below the defect-count threshold.
    """
    detections = [RawDetection(defect_type="short", confidence=0.9, bbox=_BBOX)]
    image_id = _seed_image_and_run_inference(tmp_path, monkeypatch, detections)

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.ANALYZING
    assert _stub_agent_enqueue.calls == [str(image_id)]


def test_conditional_mode_triggers_on_baseline_severity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    """`missing_hole`'s knowledge-base severity is HIGH (default `min_severity`) — triggers on
    severity alone even though it's neither a critical class nor above the count threshold.
    """
    detections = [RawDetection(defect_type="missing_hole", confidence=0.9, bbox=_BBOX)]
    image_id = _seed_image_and_run_inference(tmp_path, monkeypatch, detections)

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.ANALYZING
    assert _stub_agent_enqueue.calls == [str(image_id)]


def test_conditional_mode_does_not_trigger_when_no_condition_met(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    detections = [RawDetection(defect_type="mouse_bite", confidence=0.9, bbox=_BBOX)]
    image_id = _seed_image_and_run_inference(tmp_path, monkeypatch, detections)

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED
    assert _stub_agent_enqueue.calls == []


# --- Policy Honored: always / on_demand ---------------------------------------------------------


def test_always_mode_triggers_on_a_single_low_severity_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    _run(_set_config("agent_analysis_mode", "always"))
    detections = [RawDetection(defect_type="spur", confidence=0.9, bbox=_BBOX)]
    image_id = _seed_image_and_run_inference(tmp_path, monkeypatch, detections)

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.ANALYZING
    assert _stub_agent_enqueue.calls == [str(image_id)]


def test_on_demand_mode_never_triggers_automatically_even_when_conditions_are_met(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _stub_agent_enqueue: _FakeAgentAnalysisTask
) -> None:
    _run(_set_config("agent_analysis_mode", "on_demand"))
    detections = [RawDetection(defect_type="short", confidence=0.9, bbox=_BBOX) for _ in range(5)]
    image_id = _seed_image_and_run_inference(tmp_path, monkeypatch, detections)

    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED
    assert _stub_agent_enqueue.calls == []


# --- run_agent_analysis: fallback-to-baseline path -----------------------------------------------


async def _seed_analyzing_image_with_baseline(detection_count: int = 1) -> uuid.UUID:
    async with task_db_session() as db:
        model_version = ModelVersion(
            version="v1.0.0", weights_path="/weights/best.pt", is_active=True
        )
        db.add(model_version)
        await db.flush()

        image = InspectionImage(
            source="watch_folder",
            original_path="/tmp/board.jpg",
            checksum_sha256=uuid.uuid4().hex,
            status=ImageStatus.ANALYZING,
        )
        db.add(image)
        await db.flush()

        detections = []
        for _ in range(detection_count):
            detection = Detection(
                image_id=image.id,
                defect_type=DefectType.SHORT,
                bbox=_BBOX,
                confidence=Decimal("0.900"),
                is_reported=True,
                model_version_id=model_version.id,
            )
            db.add(detection)
            detections.append(detection)
        await db.flush()

        analysis = Analysis(
            image_id=image.id,
            status=AnalysisStatus.COMPLETED,
            source=AnalysisSource.KNOWLEDGE_BASE,
            per_defect=[
                {
                    "detection_id": str(d.id),
                    "description": "baseline desc",
                    "probable_causes": ["baseline cause"],
                    "suggested_solutions": ["baseline fix"],
                    "severity": "critical",
                }
                for d in detections
            ],
            severity_max=Severity.CRITICAL,
        )
        db.add(analysis)
        await db.commit()
        return image.id


def test_run_agent_analysis_falls_back_to_baseline_when_no_llm_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No LLM Configured => No Crash (issue #31): `build_llm_client` returning `None` (e.g.
    the configured provider has no client implementation yet) must degrade to "keep the
    baseline, mark COMPLETED anyway" rather than erroring.
    """
    image_id = _run(_seed_analyzing_image_with_baseline())

    async def _no_client(db: object) -> None:
        return None

    monkeypatch.setattr(pipeline_module, "build_llm_client", _no_client)

    result = run_agent_analysis.apply(args=[str(image_id)])

    assert not result.failed()
    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED

    analysis = _run(_get_analysis(image_id))
    assert analysis is not None
    assert analysis.source == AnalysisSource.KNOWLEDGE_BASE  # unchanged — baseline kept
    assert analysis.executive_summary is None


def test_run_agent_analysis_falls_back_to_baseline_when_chain_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer Loop Bounded (issue #31): an exhausted reject/revise cycle (or any other
    `AgentChainAbortedError`) falls back to the baseline with a logged reason instead of
    hanging or failing the task.
    """
    image_id = _run(_seed_analyzing_image_with_baseline())

    async def _stub_client(db: object) -> object:
        return object()

    async def _raise_aborted(client: object, **kwargs: object) -> None:
        raise AgentChainAbortedError("Reviewer rejected 2 attempt(s) without approval: bad vocab")

    monkeypatch.setattr(pipeline_module, "build_llm_client", _stub_client)
    monkeypatch.setattr(pipeline_module, "run_chain", _raise_aborted)

    result = run_agent_analysis.apply(args=[str(image_id)])

    assert not result.failed()
    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED

    analysis = _run(_get_analysis(image_id))
    assert analysis is not None
    assert analysis.source == AnalysisSource.KNOWLEDGE_BASE


def test_run_agent_analysis_swallows_unexpected_exceptions_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = _run(_seed_analyzing_image_with_baseline())

    async def _stub_client(db: object) -> object:
        return object()

    async def _raise_unexpected(client: object, **kwargs: object) -> None:
        raise RuntimeError("totally unexpected bug")

    monkeypatch.setattr(pipeline_module, "build_llm_client", _stub_client)
    monkeypatch.setattr(pipeline_module, "run_chain", _raise_unexpected)

    result = run_agent_analysis.apply(args=[str(image_id)])

    assert not result.failed()  # never crashes the task (No LLM Configured => No Crash)
    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED


# --- run_agent_analysis: successful chain enriches the baseline ---------------------------------


def test_run_agent_analysis_enriches_analysis_on_chain_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = _run(_seed_analyzing_image_with_baseline())

    from app.agents.chain import AgentChainResult

    fake_result = AgentChainResult(
        per_defect=[
            {
                "detection_id": "whatever",
                "description": "agent desc",
                "probable_causes": ["agent cause"],
                "suggested_solutions": ["agent fix"],
                "severity": "critical",
            }
        ],
        executive_summary="agent executive summary",
        disposition_recommendation=DispositionRecommendation.REWORK,
        severity_max=Severity.CRITICAL,
        llm_provider="openai_compatible",
        llm_model="local-model",
        prompt_version="v1",
        tokens_used=123,
        duration_ms=42,
    )

    async def _stub_client(db: object) -> object:
        return object()

    async def _fake_chain(client: object, **kwargs: object) -> AgentChainResult:
        return fake_result

    monkeypatch.setattr(pipeline_module, "build_llm_client", _stub_client)
    monkeypatch.setattr(pipeline_module, "run_chain", _fake_chain)

    result = run_agent_analysis.apply(args=[str(image_id)])

    assert not result.failed()
    image = _run(_get_image(image_id))
    assert image is not None
    assert image.status == ImageStatus.COMPLETED

    analysis = _run(_get_analysis(image_id))
    assert analysis is not None
    assert analysis.source == AnalysisSource.AGENTS
    assert analysis.executive_summary == "agent executive summary"
    assert analysis.disposition_recommendation == DispositionRecommendation.REWORK
    assert analysis.llm_provider == "openai_compatible"
    assert analysis.llm_model == "local-model"
    assert analysis.prompt_version == "v1"
    assert analysis.tokens_used == 123
    assert analysis.duration_ms == 42


# --- Idempotency against redelivery --------------------------------------------------------------


def test_run_agent_analysis_is_a_no_op_when_image_is_not_analyzing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = _run(_create_image(status=ImageStatus.COMPLETED))

    called = False

    async def _fail_if_called(db: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("must not be called when the image isn't ANALYZING")

    monkeypatch.setattr(pipeline_module, "build_llm_client", _fail_if_called)

    result = run_agent_analysis.apply(args=[str(image_id)])

    assert not result.failed()
    assert called is False
