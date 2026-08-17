"""What a generated report actually says.

`test_report_generation.py` covers the task path, that a file lands on disk with the expected
row count. These tests cover the content: that occurrences are numbered and carry their own
analysis, that the defect frequency is read against the whole batch and not only the boards in
the report, that the narrative degrades to computed text without an analysis model, and that
the requested language reaches every heading while the stored per board analysis is reproduced
as recorded.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pypdf
import pytest
from reportlab.lib import colors
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm_client import LLMUnavailableError
from app.core.security import hash_password
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
    DispositionRecommendation,
    ImageSource,
    ImageStatus,
    ReportType,
    Severity,
)
from app.reports import dataset as dataset_module
from app.reports import narrative as narrative_module
from app.reports.document import ReportDocument
from app.reports.generators import csv as csv_generator
from app.reports.generators import pdf as pdf_generator
from app.reports.strings import ReportLanguage, label_enum

_NOW = datetime(2026, 2, 10, 9, 0, tzinfo=UTC)

# Both dash characters the house style forbids anywhere in generated text.
_DASHES = ("—", "–")


class _StubLLM:
    """Stands in for `app.agents.llm_client.LLMClient` (a Protocol, so duck typing is the
    intended way to substitute one).
    """

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if self.payload is None:
            raise LLMUnavailableError("no analysis model configured")
        return self.payload


async def _seed_batch(db: AsyncSession) -> dict[str, uuid.UUID]:
    """One batch of four boards: `short` on two of them (three occurrences in all),
    `missing_hole` on one, and one clean board. That is the smallest shape that separates a
    recurring class from an isolated one.
    """
    user = User(
        email=f"{uuid.uuid4()}@pcb-inspect.local",
        password_hash=hash_password("correct-horse-battery"),
        full_name="Operator",
    )
    model_version = ModelVersion(
        version=f"v-{uuid.uuid4().hex[:8]}", weights_path="/weights/best.pt", is_active=True
    )
    batch = Batch(batch_number="BATCH-C")
    db.add_all([user, model_version, batch])
    await db.flush()

    ids: dict[str, uuid.UUID] = {}
    layout: list[tuple[str, list[DefectType]]] = [
        ("C1", [DefectType.SHORT, DefectType.SHORT]),
        ("C2", [DefectType.SHORT]),
        ("C3", [DefectType.MISSING_HOLE]),
        ("C4", []),
    ]
    for board_number, defect_types in layout:
        board = Board(batch_id=batch.id, board_number=board_number)
        db.add(board)
        await db.flush()
        image = InspectionImage(
            board_id=board.id,
            source=ImageSource.WATCH_FOLDER,
            original_path=f"/tmp/{uuid.uuid4()}.jpg",
            checksum_sha256=uuid.uuid4().hex,
            status=ImageStatus.COMPLETED,
            created_at=_NOW,
            processed_at=_NOW,
        )
        db.add(image)
        await db.flush()
        ids[board_number] = image.id

        detections = []
        for position, defect_type in enumerate(defect_types):
            detection = Detection(
                image_id=image.id,
                defect_type=defect_type,
                bbox={
                    "x1": 0.1 + 0.4 * position,
                    "y1": 0.1 + 0.4 * position,
                    "x2": 0.3 + 0.4 * position,
                    "y2": 0.3 + 0.4 * position,
                },
                confidence=Decimal("0.910"),
                is_reported=True,
                model_version_id=model_version.id,
            )
            db.add(detection)
            detections.append(detection)
        await db.flush()

        if not detections:
            continue

        # Reports number a board's occurrences in the same order the inspection detail screen
        # lists its detections (`Detection.id`), so the seeded analysis text is numbered that
        # way too and the assertions can name occurrence 1 and occurrence 2.
        detections.sort(key=lambda detection: detection.id)
        db.add(
            Analysis(
                image_id=image.id,
                status=AnalysisStatus.COMPLETED,
                source=AnalysisSource.AGENTS,
                # Keyed by detection_id, which is what lets the report attach the right
                # sentences to occurrence 1 rather than repeating one text per occurrence.
                per_defect=[
                    {
                        "detection_id": str(detection.id),
                        "defect_type": detection.defect_type.value,
                        "severity": Severity.HIGH.value,
                        "description": f"Occurrence {index} on {board_number} bridges two pads.",
                        "probable_causes": [f"Excess paste near occurrence {index}"],
                        "suggested_solutions": [f"Rework occurrence {index} under the scope"],
                    }
                    for index, detection in enumerate(detections, start=1)
                ],
                executive_summary=f"Board {board_number} needs attention.",
                disposition_recommendation=DispositionRecommendation.REWORK,
                severity_max=Severity.HIGH,
                review_status=AnalysisReviewStatus.PENDING,
            )
        )
        if board_number == "C1":
            db.add(
                BoardDisposition(
                    image_id=image.id,
                    decision=BoardDispositionDecision.REWORK,
                    decided_by=user.id,
                )
            )

    await db.commit()
    return ids


async def _document(
    db: AsyncSession,
    image_ids: list[uuid.UUID],
    *,
    language: ReportLanguage = ReportLanguage.EN,
    report_type: ReportType = ReportType.CONSOLIDATED,
    llm: _StubLLM | None = None,
) -> ReportDocument:
    dataset = await dataset_module.build_dataset(db, image_ids, ordered_ids=image_ids)
    narrative = await narrative_module.build_narrative(
        db, dataset, language=language, client=llm or _StubLLM()
    )
    return ReportDocument(
        type=report_type,
        language=language,
        dataset=dataset,
        narrative=narrative,
        generated_at=_NOW,
    )


# --- Dataset ---------------------------------------------------------------------------------


async def test_occurrences_are_numbered_and_carry_their_own_analysis(
    db_session: AsyncSession,
) -> None:
    ids = await _seed_batch(db_session)

    dataset = await dataset_module.build_dataset(db_session, [ids["C1"]])

    board = dataset.boards[0]
    assert [occurrence.index for occurrence in board.occurrences] == [1, 2]
    assert {occurrence.total_on_board for occurrence in board.occurrences} == {2}
    # Each occurrence gets the entry written for its own detection, so no two occurrences of
    # the same class read identically.
    descriptions = [occurrence.description for occurrence in board.occurrences]
    assert descriptions == [
        "Occurrence 1 on C1 bridges two pads.",
        "Occurrence 2 on C1 bridges two pads.",
    ]
    assert all(occurrence.position for occurrence in board.occurrences)


async def test_a_single_board_report_still_counts_the_whole_batch_behind_it(
    db_session: AsyncSession,
) -> None:
    """The individual report's frequency reasoning is the point: one board on its own cannot
    tell you whether its defect is isolated or systemic.
    """
    ids = await _seed_batch(db_session)

    dataset = await dataset_module.build_dataset(db_session, [ids["C1"]])

    assert dataset.analytics.boards_total == 1
    assert dataset.batch_number == "BATCH-C"
    assert dataset.batch_view.boards_total == 4

    by_class = {stat.defect_type: stat for stat in dataset.batch_view.by_defect_class}
    short = by_class[DefectType.SHORT]
    assert (short.occurrences, short.boards_affected, short.boards_total) == (3, 2, 4)
    assert short.is_recurring is True

    missing_hole = by_class[DefectType.MISSING_HOLE]
    assert (missing_hole.occurrences, missing_hole.boards_affected) == (1, 1)
    assert missing_hole.is_recurring is False


async def test_scope_analytics_ignores_boards_that_did_not_complete(
    db_session: AsyncSession,
) -> None:
    """RN-07: a board still processing is not evidence of anything yet, so it must not dilute
    the share of boards a defect class was seen on.
    """
    await _seed_batch(db_session)
    batch_id = (
        await db_session.execute(select(Batch.id).where(Batch.batch_number == "BATCH-C"))
    ).scalar_one()
    board = Board(batch_id=batch_id, board_number="C5")
    db_session.add(board)
    await db_session.flush()
    db_session.add(
        InspectionImage(
            board_id=board.id,
            source=ImageSource.WATCH_FOLDER,
            original_path=f"/tmp/{uuid.uuid4()}.jpg",
            checksum_sha256=uuid.uuid4().hex,
            status=ImageStatus.PROCESSING,
            created_at=_NOW,
        )
    )
    await db_session.commit()

    analytics = await dataset_module.scope_analytics(db_session, batch_number="BATCH-C")

    assert analytics is not None
    assert analytics.boards_total == 4


# --- CSV -------------------------------------------------------------------------------------


async def test_csv_writes_one_row_per_occurrence_with_its_analysis_and_the_board_decision(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    ids = await _seed_batch(db_session)
    document = await _document(db_session, [ids["C1"], ids["C2"], ids["C3"], ids["C4"]])

    path = tmp_path / "report.csv"
    written = csv_generator.write(document, path)

    import csv as csv_module

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv_module.reader(handle))

    header, data = rows[0], rows[1:]
    # 2 + 1 + 1 occurrences, plus one row for the clean board so the file also answers which
    # boards were inspected.
    assert written == 5
    assert len(data) == 5
    assert "Defect type" in header and "Probable causes" in header and "Board decision" in header

    first = dict(zip(header, data[0], strict=True))
    assert first["Board"] == "C1"
    assert first["Occurrence"] == "1/2"
    assert first["Defect type"] == "short"
    assert first["Description"] == "Occurrence 1 on C1 bridges two pads."
    assert first["Probable causes"] == "Excess paste near occurrence 1"
    assert first["Suggested solutions"] == "Rework occurrence 1 under the scope"
    assert first["Severity"] == "high"
    assert first["Recommended decision"] == "rework"
    assert first["Board decision"] == "rework"
    assert first["Analysis review"] == "PENDING"

    clean = dict(zip(header, data[-1], strict=True))
    assert clean["Board"] == "C4"
    assert clean["Defect type"] == ""


async def test_csv_headers_follow_the_requested_language(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    ids = await _seed_batch(db_session)
    document = await _document(db_session, [ids["C1"]], language=ReportLanguage.PT)

    path = tmp_path / "relatorio.csv"
    csv_generator.write(document, path)
    header = path.read_text(encoding="utf-8-sig").splitlines()[0]

    assert "Tipo de defeito" in header
    assert "Causas prováveis" in header
    # The analysis stored for the board is reproduced as recorded, never re-translated.
    assert "Occurrence 1 on C1 bridges two pads." in path.read_text(encoding="utf-8-sig")


async def test_defect_class_names_are_not_translated_in_a_portuguese_report(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The defect classes keep their names in every language, on every surface. A Portuguese
    report that renamed them would be the only place in the application calling the same
    defect something else than the screens, the charts and the chat do.
    """
    ids = await _seed_batch(db_session)
    document = await _document(db_session, [ids["C1"]], language=ReportLanguage.PT)

    path = tmp_path / "relatorio.csv"
    csv_generator.write(document, path)
    body = path.read_text(encoding="utf-8-sig")

    # The column heading is translated; the class name inside the column is not.
    assert "Tipo de defeito" in body
    assert "short" in body
    assert "curto" not in body.lower()

    for defect_type in DefectType:
        assert label_enum(ReportLanguage.PT, defect_type) == defect_type.value.replace("_", " ")
        assert label_enum(ReportLanguage.PT, defect_type) == label_enum(
            ReportLanguage.EN, defect_type
        )


# --- Narrative -------------------------------------------------------------------------------


async def test_narrative_falls_back_to_computed_text_when_no_model_answers(
    db_session: AsyncSession,
) -> None:
    ids = await _seed_batch(db_session)
    dataset = await dataset_module.build_dataset(db_session, [ids["C1"], ids["C2"], ids["C3"]])

    narrative = await narrative_module.build_narrative(
        db_session, dataset, language=ReportLanguage.EN, client=_StubLLM()
    )

    assert narrative.written_by_model is False
    assert narrative.overview
    # The frequency reading is the substance of the note, and it separates the two classes.
    short_note = narrative.note_for(DefectType.SHORT)
    missing_note = narrative.note_for(DefectType.MISSING_HOLE)
    assert short_note is not None and "shared upstream" in short_note
    assert missing_note is not None and "isolated occurrence" in missing_note
    assert narrative.recommendations


async def test_narrative_written_by_the_model_keeps_a_note_for_every_defect_class(
    db_session: AsyncSession,
) -> None:
    """A model that answers about one class only must not leave the frequency section with a
    hole in it, so the computed note stands in for whatever it skipped.
    """
    ids = await _seed_batch(db_session)
    dataset = await dataset_module.build_dataset(db_session, [ids["C1"], ids["C2"], ids["C3"]])
    stub = _StubLLM(
        {
            "overview": "Three boards carry defects in this batch.",
            "defect_notes": [{"defect_type": "short", "note": "Short repeats across boards."}],
            "recommendations": ["Check the stencil aperture."],
        }
    )

    narrative = await narrative_module.build_narrative(
        db_session, dataset, language=ReportLanguage.EN, client=stub
    )

    assert narrative.written_by_model is True
    assert narrative.overview == "Three boards carry defects in this batch."
    assert narrative.note_for(DefectType.SHORT) == "Short repeats across boards."
    assert narrative.note_for(DefectType.MISSING_HOLE) is not None
    # The model is given the counts it is meant to interpret, never asked to recall them.
    _system, facts = stub.calls[0]
    assert "BATCH-C" in facts
    assert "short" in facts


async def test_narrative_prompt_carries_the_analyses_already_stored_in_the_database(
    db_session: AsyncSession,
) -> None:
    """The report's own summary is a synthesis of the analyses the chain already wrote, not a
    second opinion over the same counts, so those analyses have to reach the prompt.
    """
    ids = await _seed_batch(db_session)
    dataset = await dataset_module.build_dataset(
        db_session, [ids["C1"], ids["C2"], ids["C3"], ids["C4"]]
    )
    stub = _StubLLM(
        {
            "overview": "Short dominates this batch.",
            "defect_notes": [],
            "recommendations": [],
        }
    )

    await narrative_module.build_narrative(
        db_session, dataset, language=ReportLanguage.EN, client=stub
    )

    system, facts = stub.calls[0]
    assert "already recorded" in system  # the model is told what that material is
    # The stored board summary, the per occurrence text, and the causes/solutions the agents
    # proposed, grouped under the defect class they belong to.
    assert "Board C1 needs attention." in facts
    assert "Occurrence 2 on C1 bridges two pads." in facts
    assert "Rework occurrence 1 under the scope" in facts
    assert "Recorded analysis for short" in facts
    # C1 and C2 both recorded the same cause for their first occurrence: the report never sees
    # it twice, it sees it once with the repetition counted.
    assert "Excess paste near occurrence 1 (recorded 2 times)" in facts


async def test_narrative_never_emits_dashes(db_session: AsyncSession) -> None:
    ids = await _seed_batch(db_session)
    dataset = await dataset_module.build_dataset(db_session, [ids["C1"], ids["C2"]])
    stub = _StubLLM(
        {
            "overview": "Two boards inspected — both carry a short.",
            "defect_notes": [{"defect_type": "short", "note": "Short – seen twice."}],
            "recommendations": ["Review the paste — then release."],
        }
    )

    narrative = await narrative_module.build_narrative(
        db_session, dataset, language=ReportLanguage.EN, client=stub
    )

    text = " ".join(
        [narrative.overview, *narrative.defect_notes.values(), *narrative.recommendations]
    )
    assert not any(dash in text for dash in _DASHES)


# --- PDF -------------------------------------------------------------------------------------


def _pdf_text(path: Path) -> str:
    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _outline_titles(items: Any) -> list[str]:
    """Bookmark titles, flattened: pypdf nests sub-bookmarks as inner lists."""
    titles: list[str] = []
    for item in items:
        if isinstance(item, list):
            titles.extend(_outline_titles(item))
        else:
            titles.append(str(item.get("/Title")))
    return titles


async def test_pdf_has_a_contents_page_and_outline_bookmarks(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    ids = await _seed_batch(db_session)
    document = await _document(db_session, [ids["C1"], ids["C2"], ids["C3"], ids["C4"]])

    path = tmp_path / "report.pdf"
    pdf_generator.write(document, path)

    reader = pypdf.PdfReader(str(path))
    assert len(reader.outline) > 0, "the PDF must be navigable from the reader's bookmark pane"
    # Bookmarks have to read as their headings. reportlab keys the title map by the destination
    # name, so passing that name as bytes silently leaves every bookmark labelled "sec-1".
    outline_titles = _outline_titles(reader.outline)
    assert "Executive summary" in outline_titles
    assert "Defect frequency across the batch" in outline_titles
    assert not any(title.startswith("sec-") for title in outline_titles)

    text = _pdf_text(path)
    assert "Contents" in text
    assert "Executive summary" in text
    assert "Defect frequency across the batch" in text
    # The detections table the operator asked to keep.
    assert "Confidence" in text and "Review" in text and "Source" in text
    # Occurrences are cited individually rather than repeated as one block per class.
    assert "Occurrence 1 of 2" in text
    assert "Occurrence 2 of 2" in text
    assert not any(dash in text for dash in _DASHES)


async def test_pdf_is_written_in_the_requested_language(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    ids = await _seed_batch(db_session)
    document = await _document(db_session, [ids["C1"], ids["C2"]], language=ReportLanguage.PT)

    path = tmp_path / "relatorio.pdf"
    pdf_generator.write(document, path)
    text = _pdf_text(path)

    assert "Sumário" in text
    assert "Resumo executivo" in text
    assert "Frequência dos defeitos no lote" in text
    # Reviewed analysis text is reproduced as recorded, in the language it was written in.
    assert "bridges two pads" in text
    # The position phrase is computed at generation time, not stored, so it follows the
    # requested language instead of staying in the prompts' English.
    assert "com centro em x=" in text
    assert "centred at" not in text


async def test_individual_pdf_reports_a_single_board_against_its_batch(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The per board report keeps existing, with the same rework as the batch one."""
    ids = await _seed_batch(db_session)
    document = await _document(db_session, [ids["C1"]], report_type=ReportType.INDIVIDUAL)

    path = tmp_path / "individual.pdf"
    pdf_generator.write(document, path)
    text = _pdf_text(path)

    assert "Board Inspection Report" in text
    assert "C1" in text
    # One board in the report, four in the batch it is read against.
    assert "Occurrence 1 of 2" in text
    assert "4" in text


@pytest.mark.parametrize("language", [ReportLanguage.EN, ReportLanguage.PT])
async def test_empty_scope_still_produces_a_readable_pdf(
    db_session: AsyncSession, tmp_path: Path, language: ReportLanguage
) -> None:
    """A filter that matches nothing has to say so, not fail generation."""
    document = await _document(db_session, [], language=language)

    path = tmp_path / f"empty-{language.value}.pdf"
    pdf_generator.write(document, path)

    assert path.read_bytes().startswith(b"%PDF")
    assert _pdf_text(path).strip()


def test_table_header_text_is_light_enough_to_read_on_the_dark_band() -> None:
    """The header row is drawn on `_HEADER_BG` (near black). Every cell is a `Paragraph`, and a
    `TableStyle` TEXTCOLOR command does not reach text inside a flowable, so the white has to
    come from the paragraph's own style. It did not, and the column titles rendered near black
    on near black, which is what an operator reported as an unreadable first row.
    """
    header = ["Board", "Defect type", "Severity"]
    table = pdf_generator._data_table(header, [["A1", "short", "high"]], [4.0, 4.0, 4.0])

    header_cells = table._cellvalues[0]
    assert [cell.getPlainText() for cell in header_cells] == header
    for cell in header_cells:
        assert cell.style.textColor == colors.white, cell.getPlainText()
        assert cell.style.fontName == "Helvetica-Bold"

    # The body rows keep the dark ink they are drawn on white/banded backgrounds with.
    body_cell = table._cellvalues[1][0]
    assert body_cell.style.textColor == pdf_generator._INK


async def test_narrative_prompt_forbids_translating_the_defect_class_names(
    db_session: AsyncSession,
) -> None:
    """The tables print the class names unchanged in every language, so the prose written
    beside them has to as well: a Portuguese report that says "3 curtos" over a table that says
    "short" is reporting two different things to the same engineer.
    """
    ids = await _seed_batch(db_session)
    dataset = await dataset_module.build_dataset(db_session, [ids["C1"], ids["C2"]])
    stub = _StubLLM({"overview": "ok", "defect_notes": [], "recommendations": []})

    await narrative_module.build_narrative(
        db_session, dataset, language=ReportLanguage.PT, client=stub
    )

    system, _facts = stub.calls[0]
    assert "never translated" in system
    for defect_type in DefectType:
        assert defect_type.value in system
