"""Analyst -> Reviewer -> Summarizer chain unit tests (PRD 5.3, issue #31). A stub LLM client
drives every response deterministically — no real network dependency, per issue #31's "Tests"
acceptance criterion.
"""

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.agents.chain import run_chain
from app.agents.errors import AgentChainAbortedError
from app.models import Detection
from app.models.enums import DefectType, DispositionRecommendation, Severity


def _detection(defect_type: DefectType = DefectType.SHORT) -> Detection:
    return Detection(
        id=uuid.uuid4(),
        image_id=uuid.uuid4(),
        defect_type=defect_type,
        bbox={"x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4},
        confidence=Decimal("0.900"),
        is_reported=True,
        model_version_id=uuid.uuid4(),
    )


class _StubLLMClient:
    """Returns a scripted sequence of JSON-object responses, one per call, in order
    (Analyst, Reviewer, [Analyst, Reviewer, ...], Summarizer) — raises if called more times
    than scripted, so a test's response list doubles as an exact call-count assertion.
    """

    provider = "stub"
    model = "stub-model"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("stub LLM client called more times than scripted")
        return self._responses.pop(0)


def _analyst_response(detection_id: uuid.UUID, severity: str = "high") -> dict[str, Any]:
    return {
        "findings": [
            {
                "detection_id": str(detection_id),
                "description": "desc",
                "probable_causes": ["cause"],
                "suggested_solutions": ["fix"],
                "severity": severity,
                "functional_impact": "impact",
            }
        ]
    }


def _approve_response() -> dict[str, Any]:
    return {"approved": True, "corrections": [], "revised_findings": None}


def _reject_response(reason: str = "wrong vocabulary") -> dict[str, Any]:
    return {"approved": False, "corrections": [reason], "revised_findings": None}


def _summary_response() -> dict[str, Any]:
    return {
        "executive_summary": "summary",
        "disposition_recommendation": "rework",
        "priority": "high",
    }


async def test_run_chain_happy_path_approves_first_draft() -> None:
    detection = _detection()
    client = _StubLLMClient(
        [_analyst_response(detection.id), _approve_response(), _summary_response()]
    )

    result = await run_chain(
        client, board_number="B1", batch_number="BATCH1", detections=[detection]
    )

    assert len(client.calls) == 3
    assert result.per_defect == [
        {
            "detection_id": str(detection.id),
            "description": "desc",
            "probable_causes": ["cause"],
            "suggested_solutions": ["fix"],
            "severity": "high",
        }
    ]
    assert result.executive_summary == "summary"
    assert result.disposition_recommendation == DispositionRecommendation.REWORK
    assert result.severity_max == Severity.HIGH
    assert result.llm_provider == "stub"
    assert result.llm_model == "stub-model"
    assert result.prompt_version == "v1"
    assert result.duration_ms >= 0


async def test_run_chain_revises_once_after_a_rejection() -> None:
    detection = _detection()
    client = _StubLLMClient(
        [
            _analyst_response(detection.id, severity="critical"),
            _reject_response("severity too high for a spur"),
            _analyst_response(detection.id, severity="medium"),
            _approve_response(),
            _summary_response(),
        ]
    )

    result = await run_chain(
        client,
        board_number="B1",
        batch_number="BATCH1",
        detections=[detection],
        max_review_attempts=2,
    )

    assert len(client.calls) == 5
    assert result.per_defect[0]["severity"] == "medium"
    # The revision request must actually carry the reviewer's correction forward.
    revision_user_prompt = client.calls[2][1]
    assert "severity too high for a spur" in revision_user_prompt


async def test_run_chain_raises_after_exhausting_max_review_attempts() -> None:
    """Reviewer Loop Bounded (issue #31): a reject/revise cycle terminates within the
    configured max attempts rather than looping forever.
    """
    detection = _detection()
    client = _StubLLMClient(
        [
            _analyst_response(detection.id),
            _reject_response("first rejection"),
            _analyst_response(detection.id),
            _reject_response("second rejection"),
        ]
    )

    with pytest.raises(AgentChainAbortedError, match="second rejection"):
        await run_chain(
            client,
            board_number="B1",
            batch_number="BATCH1",
            detections=[detection],
            max_review_attempts=2,
        )

    assert len(client.calls) == 4  # never reaches the Summarizer once the chain gives up


async def test_run_chain_uses_revised_findings_when_reviewer_provides_them() -> None:
    detection = _detection()
    revised = {
        "detection_id": str(detection.id),
        "description": "corrected desc",
        "probable_causes": ["corrected cause"],
        "suggested_solutions": ["corrected fix"],
        "severity": "low",
        "functional_impact": "corrected impact",
    }
    client = _StubLLMClient(
        [
            _analyst_response(detection.id),
            {"approved": True, "corrections": [], "revised_findings": [revised]},
            _summary_response(),
        ]
    )

    result = await run_chain(
        client, board_number="B1", batch_number="BATCH1", detections=[detection]
    )

    assert result.per_defect[0]["description"] == "corrected desc"
    assert result.severity_max == Severity.LOW


async def test_run_chain_aborts_on_malformed_analyst_output() -> None:
    detection = _detection()
    client = _StubLLMClient([{"not": "the expected shape"}])

    with pytest.raises(AgentChainAbortedError):
        await run_chain(client, board_number="B1", batch_number="BATCH1", detections=[detection])


async def test_run_chain_aborts_on_detection_id_mismatch() -> None:
    """A hallucinated/omitted detection_id must abort rather than silently persist a finding
    set that doesn't match the ground-truth detections.
    """
    detection = _detection()
    client = _StubLLMClient([_analyst_response(uuid.uuid4())])

    with pytest.raises(AgentChainAbortedError, match="mismatch"):
        await run_chain(client, board_number="B1", batch_number="BATCH1", detections=[detection])


async def test_run_chain_rejects_empty_detections() -> None:
    client = _StubLLMClient([])
    with pytest.raises(AgentChainAbortedError):
        await run_chain(client, board_number=None, batch_number=None, detections=[])


async def test_run_chain_rejects_non_positive_max_review_attempts() -> None:
    detection = _detection()
    client = _StubLLMClient([])
    with pytest.raises(AgentChainAbortedError):
        await run_chain(
            client,
            board_number=None,
            batch_number=None,
            detections=[detection],
            max_review_attempts=0,
        )


class _RaisingLLMClient:
    """Simulates an unreachable LLM (e.g. no local server running behind the configured
    endpoint — Phase 1's default demo state) via a client-level failure rather than a
    malformed response.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        raise self._exc


async def test_run_chain_aborts_gracefully_when_llm_is_unreachable() -> None:
    from app.agents.llm_client import LLMUnavailableError

    detection = _detection()
    client = _RaisingLLMClient(LLMUnavailableError("connection refused"))

    with pytest.raises(AgentChainAbortedError, match="connection refused"):
        await run_chain(client, board_number="B1", batch_number="BATCH1", detections=[detection])
