from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import User
from app.retention import service
from app.retention.schemas import RetentionPurgePreview

router = APIRouter(prefix="/api/v1/retention", tags=["retention"])


@router.get("/preview", response_model=RetentionPurgePreview)
async def preview_purge(
    db: AsyncSession = Depends(get_db), _current_user: User = Depends(get_current_user)
) -> RetentionPurgePreview:
    """Dry-run — what the next scheduled `purge_expired` run would delete, given the current
    retention config (FR-17's "verify a policy change before it runs for real" requirement).
    """
    summary = await service.preview_purge(db)
    return RetentionPurgePreview(cutoffs=summary.cutoffs, counts=summary.counts)
