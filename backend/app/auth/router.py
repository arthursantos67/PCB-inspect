from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.schemas import LoginRequest, RefreshRequest, SetupRequest, SetupStatus, TokenResponse
from app.db.session import get_db
from app.users.schemas import UserRead

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/setup", response_model=SetupStatus)
async def get_setup_status(db: AsyncSession = Depends(get_db)) -> SetupStatus:
    return SetupStatus(setup_required=not await service.any_account_exists(db))


@router.post("/setup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def setup(payload: SetupRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await service.create_initial_account(
        db, email=payload.email, password=payload.password, full_name=payload.full_name
    )
    access_token, refresh_token, expires_in = service.issue_tokens(user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await service.authenticate(db, email=payload.email, password=payload.password)
    access_token, refresh_token, expires_in = service.issue_tokens(user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await service.user_from_refresh_token(db, refresh_token=payload.refresh_token)
    access_token, refresh_token, expires_in = service.issue_tokens(user)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserRead.model_validate(user),
    )
