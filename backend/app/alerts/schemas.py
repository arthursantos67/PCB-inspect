import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, computed_field

from app.models.enums import QualityAlertType

AlertStatus = Literal["active", "acknowledged"]


class AlertOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    type: QualityAlertType
    context: dict[str, Any]
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> AlertStatus:
        return "active" if self.acknowledged_at is None else "acknowledged"


class PaginatedAlerts(BaseModel):
    """Pagination envelope per PRD section 11.1, same shape as `PaginatedReports`."""

    count: int
    next: str | None
    previous: str | None
    results: list[AlertOut]
