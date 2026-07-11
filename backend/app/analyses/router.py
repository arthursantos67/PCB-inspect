import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyses import service
from app.analyses.schemas import AnalysisOut
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])


@router.get("/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(
    analysis_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AnalysisOut:
    analysis = await service.get_analysis(db, analysis_id)
    return AnalysisOut.model_validate(analysis)
