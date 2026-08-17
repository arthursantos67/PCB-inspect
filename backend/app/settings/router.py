from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models import User
from app.settings import service
from app.settings.schemas import ConfigResponse, ConfigUpdateRequest, DirectoryListing

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("/config", response_model=ConfigResponse)
async def get_config(
    db: AsyncSession = Depends(get_db), _current_user: User = Depends(get_current_user)
) -> ConfigResponse:
    return ConfigResponse(config=await service.get_all_config(db))


@router.get("/browse", response_model=DirectoryListing)
async def browse(
    path: str | None = Query(default=None),
    _current_user: User = Depends(get_current_user),
) -> DirectoryListing:
    """Lists subdirectories of a host folder, so Settings > Ingestion can offer a folder picker
    instead of asking the operator to type an absolute path (FR-20).
    """
    return await service.list_directories(path)


@router.patch("/config", response_model=ConfigResponse)
async def patch_config(
    payload: ConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConfigResponse:
    config = await service.update_config(db, actor_id=current_user.id, updates=payload.config)
    return ConfigResponse(config=config)
