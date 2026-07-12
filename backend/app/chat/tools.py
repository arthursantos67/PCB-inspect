"""The chat agent's fixed, read-only tool set (PRD 5.4, FR-09) — every one of these queries
production data directly from the database; there is no other channel through which the chat
agent can learn a fact about production data (`app.chat.agent`). None of them has write access,
per issue #32's scope note.

Each tool is described twice: an OpenAI-compatible function-calling schema (`TOOL_SCHEMAS`,
sent to the LLM so it knows what it can call and with which arguments) and an async executor
(`TOOL_EXECUTORS`, what actually runs when the LLM asks to call it). Every executor returns a
plain JSON-serializable dict — this is what gets fed back into the conversation as the tool's
result message.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.inspections.filters import InspectionFilters, apply_filters, order_by_clauses
from app.knowledge.defects import DEFECT_KNOWLEDGE_BASE
from app.models import Analysis, Batch, Board, Detection, InspectionImage
from app.models.enums import DefectType, ImageStatus

_MAX_RESULTS = 20


def _inspection_query(*entities: Any) -> Select[Any]:
    """Mirrors `app.inspections.router._base_query` — kept as its own copy rather than
    importing that (module-private) helper across a package boundary.
    """
    return (
        select(*entities)
        .select_from(InspectionImage)
        .outerjoin(Board, InspectionImage.board_id == Board.id)
        .outerjoin(Batch, Board.batch_id == Batch.id)
        .outerjoin(Analysis, Analysis.image_id == InspectionImage.id)
    )


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


async def search_analyses(db: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    """Search inspections/analyses by batch, board, defect type, period, status (PRD 5.4)."""
    defect_type = arguments.get("defect_type")
    filters = InspectionFilters(
        defect_type=[DefectType(defect_type)] if defect_type else None,
        batch_number=arguments.get("batch_number"),
        board_number=arguments.get("board_number"),
        status=ImageStatus(arguments["status"]) if arguments.get("status") else None,
        date_from=_parse_date(arguments.get("date_from")),
        date_to=_parse_date(arguments.get("date_to")),
    )
    limit = min(int(arguments.get("limit") or 10), _MAX_RESULTS)

    stmt = (
        apply_filters(_inspection_query(InspectionImage, Board, Batch, Analysis), filters)
        .order_by(*order_by_clauses("-created_at"))
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    return {
        "count": len(rows),
        "results": [
            {
                "inspection_id": str(image.id),
                "batch_number": batch.batch_number if batch is not None else None,
                "board_number": board.board_number if board is not None else None,
                "status": image.status.value,
                "severity_max": (
                    analysis.severity_max.value if analysis and analysis.severity_max else None
                ),
                "disposition_recommendation": (
                    analysis.disposition_recommendation.value
                    if analysis and analysis.disposition_recommendation
                    else None
                ),
                "created_at": image.created_at.isoformat(),
            }
            for image, board, batch, analysis in rows
        ],
    }


async def get_analysis(db: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    """Full detail of one analysis, by inspection id (PRD 5.4)."""
    inspection_id_raw = arguments.get("inspection_id")
    try:
        inspection_id = uuid.UUID(str(inspection_id_raw))
    except (TypeError, ValueError):
        return {"error": f"'{inspection_id_raw}' is not a valid inspection id"}

    row = (
        await db.execute(
            select(InspectionImage, Board, Batch, Analysis)
            .select_from(InspectionImage)
            .outerjoin(Board, InspectionImage.board_id == Board.id)
            .outerjoin(Batch, Board.batch_id == Batch.id)
            .outerjoin(Analysis, Analysis.image_id == InspectionImage.id)
            .where(InspectionImage.id == inspection_id)
        )
    ).first()
    if row is None:
        return {"error": f"No inspection found with id '{inspection_id}'"}
    image, board, batch, analysis = row

    detections = (
        await db.execute(
            select(Detection)
            .where(Detection.image_id == inspection_id, Detection.is_reported.is_(True))
            .order_by(Detection.id)
        )
    ).scalars().all()

    return {
        "inspection_id": str(image.id),
        "batch_number": batch.batch_number if batch is not None else None,
        "board_number": board.board_number if board is not None else None,
        "status": image.status.value,
        "detections": [
            {"defect_type": d.defect_type.value, "confidence": float(d.confidence)}
            for d in detections
        ],
        "analysis": (
            {
                "status": analysis.status.value,
                "source": analysis.source.value,
                "severity_max": analysis.severity_max.value if analysis.severity_max else None,
                "executive_summary": analysis.executive_summary,
                "disposition_recommendation": (
                    analysis.disposition_recommendation.value
                    if analysis.disposition_recommendation
                    else None
                ),
                "per_defect": analysis.per_defect,
            }
            if analysis is not None
            else None
        ),
    }


async def get_defect_stats(db: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    """Aggregated statistics: counts by defect type, or top batches by defect count (PRD 5.4).
    `group_by` picks the aggregation dimension the operator's question needs — natural-language
    questions ("which batches...") don't map onto the dashboard's fixed cache keys
    (`app.stats.service`), so this aggregates directly rather than reusing that cache.
    """
    date_from = _parse_date(arguments.get("date_from"))
    date_to = _parse_date(arguments.get("date_to"))
    group_by = arguments.get("group_by") or "defect_type"
    limit = min(int(arguments.get("limit") or 5), _MAX_RESULTS)

    conditions = [Detection.is_reported.is_(True), InspectionImage.status == ImageStatus.COMPLETED]
    if date_from is not None:
        conditions.append(InspectionImage.created_at >= date_from)
    if date_to is not None:
        conditions.append(InspectionImage.created_at <= date_to)

    if group_by == "batch":
        by_batch_stmt = (
            select(Batch.batch_number, func.count(Detection.id))
            .select_from(Detection)
            .join(InspectionImage, Detection.image_id == InspectionImage.id)
            .join(Board, InspectionImage.board_id == Board.id)
            .join(Batch, Board.batch_id == Batch.id)
            .where(*conditions)
            .group_by(Batch.batch_number)
            .order_by(func.count(Detection.id).desc())
            .limit(limit)
        )
        batch_rows = (await db.execute(by_batch_stmt)).all()
        return {
            "group_by": "batch",
            "results": [{"batch_number": b, "defect_count": c} for b, c in batch_rows],
        }

    by_defect_type_stmt = (
        select(Detection.defect_type, func.count(Detection.id))
        .select_from(Detection)
        .join(InspectionImage, Detection.image_id == InspectionImage.id)
        .where(*conditions)
        .group_by(Detection.defect_type)
        .order_by(func.count(Detection.id).desc())
    )
    defect_type_rows = (await db.execute(by_defect_type_stmt)).all()
    return {
        "group_by": "defect_type",
        "results": [{"defect_type": dt.value, "defect_count": c} for dt, c in defect_type_rows],
    }


async def get_defect_knowledge(db: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    """Static knowledge base on the 6 defect types (PRD 5.4) — no DB access needed, but kept
    to the same `(db, arguments) -> dict` executor signature as every other tool.
    """
    defect_type_raw = arguments.get("defect_type")
    try:
        defect_type = DefectType(str(defect_type_raw))
    except ValueError:
        allowed = ", ".join(member.value for member in DefectType)
        return {"error": f"'{defect_type_raw}' is not one of the known defect types: {allowed}"}

    entry = DEFECT_KNOWLEDGE_BASE[defect_type]
    return {
        "defect_type": defect_type.value,
        "description": entry.description,
        "probable_causes": list(entry.probable_causes),
        "suggested_solutions": list(entry.suggested_solutions),
        "default_severity": entry.severity.value,
    }


ToolExecutor = Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]

TOOL_EXECUTORS: dict[str, ToolExecutor] = {
    "search_analyses": search_analyses,
    "get_analysis": get_analysis,
    "get_defect_stats": get_defect_stats,
    "get_defect_knowledge": get_defect_knowledge,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_analyses",
            "description": (
                "Search inspections/analyses by batch, board, defect type, date range, or "
                "processing status. Returns a list of matching inspections, most recent first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "defect_type": {
                        "type": "string",
                        "enum": [member.value for member in DefectType],
                        "description": "Filter by one of the six known defect classes.",
                    },
                    "batch_number": {"type": "string", "description": "Exact batch number."},
                    "board_number": {"type": "string", "description": "Exact board number."},
                    "status": {
                        "type": "string",
                        "enum": [member.value for member in ImageStatus],
                        "description": "Processing status.",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "ISO 8601 datetime; only inspections created on/after this.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": (
                            "ISO 8601 datetime; only inspections created on/before this."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Max results to return (default 10, max {_MAX_RESULTS}).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_analysis",
            "description": (
                "Get the full detail of one specific inspection/analysis by its id, "
                "including detections and the AI analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inspection_id": {"type": "string", "description": "The inspection's UUID."},
                },
                "required": ["inspection_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_defect_stats",
            "description": (
                "Aggregated statistics over reported defects: total counts per defect type, "
                "or the top batches by defect count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "group_by": {
                        "type": "string",
                        "enum": ["defect_type", "batch"],
                        "description": (
                            "Aggregation dimension. Use 'batch' for questions like "
                            "'which batches had the most defects'."
                        ),
                    },
                    "date_from": {
                        "type": "string",
                        "description": "ISO 8601 datetime lower bound.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "ISO 8601 datetime upper bound.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"Max groups to return when group_by='batch' "
                            f"(default 5, max {_MAX_RESULTS})."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_defect_knowledge",
            "description": (
                "Static reference knowledge about one of the six defect types: definition, "
                "typical causes, and standard solutions. Does not query production data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "defect_type": {
                        "type": "string",
                        "enum": [member.value for member in DefectType],
                    },
                },
                "required": ["defect_type"],
            },
        },
    },
]


async def execute_tool(db: AsyncSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    executor = TOOL_EXECUTORS.get(name)
    if executor is None:
        raise ApiError("INTERNAL_SERVER_ERROR", f"Unknown tool requested: {name}", 500)
    return await executor(db, arguments)
