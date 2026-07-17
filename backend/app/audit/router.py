import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service
from app.audit.schemas import AuditActorOut, AuditLogOut, PaginatedAuditLog
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/api/v1/settings/audit", tags=["audit"])

MAX_PAGE_SIZE = service.MAX_PAGE_SIZE


def _page_url(request: Request, page: int, page_size: int) -> str:
    return str(request.url.include_query_params(page=page, page_size=page_size))


@router.get("", response_model=PaginatedAuditLog)
async def list_audit_log(
    request: Request,
    account_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedAuditLog:
    """Read side of the audit trail (FR-16), most recent first — combinable filters by
    account, action, and creation-date range. The write side (`record_audit`) is
    unconditional and append-only (RN-06); no account has more visibility into it than
    another (PRD 2.2).
    """
    count, rows = await service.query_audit_log(
        db,
        account_id=account_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    results = [
        AuditLogOut(
            id=entry.id,
            actor=AuditActorOut.model_validate(actor) if actor is not None else None,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            payload=entry.payload,
            created_at=entry.created_at,
        )
        for entry, actor in rows
    ]
    return PaginatedAuditLog(
        count=count,
        next=_page_url(request, page + 1, page_size) if page * page_size < count else None,
        previous=_page_url(request, page - 1, page_size) if page > 1 else None,
        results=results,
    )
