import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses import service
from app.analyses.schemas import AnalysisOut, AnalysisReviewOut, ReviewRequest
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import Analysis, User

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])


async def _to_analysis_out(db: AsyncSession, analysis: Analysis) -> AnalysisOut:
    reviews = await service.list_analysis_reviews(db, analysis.id)
    out = AnalysisOut.model_validate(analysis)
    out.reviews = [AnalysisReviewOut.model_validate(review) for review in reviews]
    return out


@router.get("/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AnalysisOut:
    analysis = await service.get_analysis(db, analysis_id)
    return await _to_analysis_out(db, analysis)


@router.post("/{analysis_id}/review", response_model=AnalysisOut)
async def review_analysis(
    analysis_id: uuid.UUID,
    payload: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysisOut:
    """Validate/reject an analysis with an optional comment (FR-10, UC-8) — audited (FR-16)
    and feeds the validated-vs-rejected precision metric (`GET /api/v1/stats/summary`).
    """
    analysis = await service.review_analysis(
        db,
        actor_id=current_user.id,
        analysis_id=analysis_id,
        action=payload.action,
        comment=payload.comment,
    )
    return await _to_analysis_out(db, analysis)
