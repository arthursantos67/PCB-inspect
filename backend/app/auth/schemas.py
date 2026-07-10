from pydantic import BaseModel, Field

from app.users.schemas import EmailAddress, UserRead


class SetupStatus(BaseModel):
    setup_required: bool


class SetupRequest(BaseModel):
    email: EmailAddress
    password: str = Field(min_length=10)
    full_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: EmailAddress
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
