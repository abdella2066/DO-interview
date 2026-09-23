"""Domain errors, plus handlers that turn every failure into the same JSON error shape:

{"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FlagNotFoundError(AppError):
    status_code = 404
    code = "FLAG_NOT_FOUND"

    def __init__(self, key: str) -> None:
        super().__init__(f"Flag '{key}' does not exist")


class OverrideNotFoundError(AppError):
    status_code = 404
    code = "OVERRIDE_NOT_FOUND"

    def __init__(self, key: str, user_id: str) -> None:
        super().__init__(f"Flag '{key}' has no override for user '{user_id}'")


class FlagAlreadyExistsError(AppError):
    status_code = 409
    code = "FLAG_ALREADY_EXISTS"

    def __init__(self, key: str) -> None:
        super().__init__(f"Flag '{key}' already exists")


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": getattr(request.state, "request_id", None),
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        if any(error["type"] == "json_invalid" for error in errors):
            return error_response(request, 400, "MALFORMED_JSON", "Request body is not valid JSON")
        details = [
            {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
            for error in errors
        ]
        return error_response(
            request, 422, "VALIDATION_ERROR", "Request validation failed", details
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Raised by the framework itself, e.g. unknown routes (404) and wrong methods (405).
        code = HTTPStatus(exc.status_code).name
        return error_response(request, exc.status_code, code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(OperationalError)
    async def handle_database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
        logger.error("Database unavailable: %s", exc)
        message = "The database is unavailable; try again shortly"
        return error_response(request, 503, "SERVICE_UNAVAILABLE", message)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(request, 500, "INTERNAL_ERROR", "An unexpected error occurred")
