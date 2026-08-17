from typing import Any

from pydantic import BaseModel


class ConfigUpdateRequest(BaseModel):
    config: dict[str, Any]


class ConfigResponse(BaseModel):
    config: dict[str, Any]


class DirectoryEntry(BaseModel):
    name: str
    path: str


class DirectoryListing(BaseModel):
    """One level of the host filesystem, for the folder picker on Settings > Ingestion.

    Only directories are listed — the operator is choosing a watch root, and the images inside
    it are the ingestion pipeline's business, not the picker's.
    """

    path: str
    parent: str | None
    directories: list[DirectoryEntry]
