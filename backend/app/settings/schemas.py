from typing import Any

from pydantic import BaseModel


class ConfigUpdateRequest(BaseModel):
    config: dict[str, Any]


class ConfigResponse(BaseModel):
    config: dict[str, Any]
