"""Standardized error envelope (PRD section 11.4): {"error": {code, message, status, details}}."""

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def _envelope(code: str, message: str, status_code: int, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "status": status_code, "details": details}
    }


def _json_safe_errors(errors: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pydantic v2 populates a raised `ValueError`'s `ctx.error` with the exception instance
    itself (for human inspection), not a JSON-serializable value — a custom
    `@model_validator` (e.g. `app.inspections.schemas.BBoxIn`) surfaces this directly, so it
    must be stringified before this goes into a `JSONResponse`.
    """
    safe = []
    for error in errors:
        ctx = error.get("ctx")
        if isinstance(ctx, dict) and isinstance(ctx.get("error"), BaseException):
            error = {**error, "ctx": {**ctx, "error": str(ctx["error"])}}
        safe.append(error)
    return safe


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.status_code, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_envelope(
                "VALIDATION_FAILED",
                "Invalid payload",
                status.HTTP_400_BAD_REQUEST,
                {"errors": _json_safe_errors(exc.errors())},
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error while processing %s %s", request.method, request.url)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                {},
            ),
        )
