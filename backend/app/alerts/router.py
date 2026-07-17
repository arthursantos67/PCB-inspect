import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import service
from app.alerts.schemas import AlertOut, PaginatedAlerts
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

MAX_PAGE_SIZE = service.MAX_PAGE_SIZE


def _page_url(request: Request, page: int, page_size: int) -> str:
    return str(request.url.include_query_params(page=page, page_size=page_size))


@router.get("", response_model=PaginatedAlerts)
async def list_alerts(
    request: Request,
    acknowledged: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PaginatedAlerts:
    """Active and historical quality alerts (FR-19), most recent first — `?acknowledged=false`
    is what the dashboard banner (FE-02) polls/subscribes to for the currently-active set.
    """
    count, alerts = await service.list_alerts(
        db, acknowledged=acknowledged, page=page, page_size=page_size
    )
    results = [AlertOut.model_validate(alert) for alert in alerts]
    return PaginatedAlerts(
        count=count,
        next=_page_url(request, page + 1, page_size) if page * page_size < count else None,
        previous=_page_url(request, page - 1, page_size) if page > 1 else None,
        results=results,
    )


@router.post("/{alert_id}/ack", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AlertOut:
    """Acknowledges an alert, audited (FR-16) — this is what clears it off the dashboard
    banner (FE-02).
    """
    alert = await service.acknowledge_alert(db, actor_id=current_user.id, alert_id=alert_id)
    return AlertOut.model_validate(alert)
