import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# A local login identifier, not a deliverable mailbox (PRD FE-01/13 — no mail server involved,
# accounts commonly use made-up domains like "operator@pcb-inspect.local"). A strict RFC/MX-aware
# validator (e.g. pydantic's EmailStr) would reject exactly that convention, so this only checks
# the shape.
EmailAddress = Annotated[
    str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailAddress
    password: str = Field(min_length=10)
    full_name: str = Field(min_length=1, max_length=200)


class UserUpdate(BaseModel):
    email: EmailAddress | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=10)
