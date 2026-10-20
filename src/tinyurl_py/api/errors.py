"""One error format for the whole API:

    {"error": {"code": "not_found", "message": "Link not found"}}

`code` is a stable word a client can switch on; `message` is for humans.
Validation errors add `details`, one entry per bad field.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status_code, content={"error": body}, headers=headers)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    # Also catches the errors FastAPI itself raises (unknown path, wrong method).
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        # The raiser chose its own code, e.g. {"code": "unsafe_destination", ...}.
        code, message = str(detail["code"]), str(detail.get("message", ""))
    else:
        code, message = _CODES.get(exc.status_code, f"http_{exc.status_code}"), str(detail)
    # Keep the headers the raiser attached (Retry-After, WWW-Authenticate).
    return _error(exc.status_code, code, message, headers=dict(exc.headers or {}))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Only where the problem is and what it is. Never `input`: the value that
    # failed may be a password somebody just typed.
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return _error(422, "validation_error", "Request validation failed", details=details)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # The full story goes to the log; the client learns nothing about our insides.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _error(500, "internal_error", "Internal server error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
