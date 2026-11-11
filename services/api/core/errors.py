"""
Error codes and the one error shape every route, stream and socket of the API answers with.

Two layers, after Google's API error model (AIP-193):

    Code     universal: one per HTTP condition, the same in every service ("rate_limited").
             A client that knows only these still handles every error correctly.
    Reason   custom: the situation inside this API ("daily_budget_spent"). Each reason belongs
             to exactly one code, so its HTTP status never varies.

The body (`error_body`):

    {"code": "rate_limited", "reason": "daily_budget_spent", "status": 429,
     "message": "today's question budget is used up", "request_id": "5f0c9a1e2b7d4c38",
     "error": <message>, "detail": <message>}

`message` is safe to show a visitor: it never holds a key, a path or a stack trace. `error` and
`detail` repeat it for the clients written before the codes existed; new code reads `message`.

Raise `AppError` in request code. Exceptions that cross module boundaries inside the service
derive from `ServiceError`, which carries the code a request should fail with if one escapes.
`install(app)` registers the handlers; docs/reference/architecture/error-codes.md lists every code.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from services.api.core.logging_config import get_logger
from services.api.core.request_context import request_id

logger = get_logger(__name__)


class Code(str, Enum):
    """Universal error codes. The value is the wire name; `status` the HTTP status."""

    def __new__(cls, value: str, status: int, message: str) -> Code:
        member = str.__new__(cls, value)
        member._value_ = value
        member.status = status
        member.message = message
        return member

    BAD_REQUEST = "bad_request", 400, "the request is not valid"
    UNAUTHENTICATED = "unauthenticated", 401, "sign in first"
    FORBIDDEN = "forbidden", 403, "not allowed"
    NOT_FOUND = "not_found", 404, "not found"
    METHOD_NOT_ALLOWED = "method_not_allowed", 405, "this method is not served here"
    CONFLICT = "conflict", 409, "the state changed: reload and try again"
    GONE = "gone", 410, "no longer available"
    PAYLOAD_TOO_LARGE = "payload_too_large", 413, "the request is too large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type", 415, "this content type is not accepted"
    VALIDATION_FAILED = "validation_failed", 422, "the request's fields are not valid"
    RATE_LIMITED = "rate_limited", 429, "too many requests: wait a few seconds"
    INTERNAL = "internal", 500, "an unexpected error occurred processing your request"
    UPSTREAM_FAILED = "upstream_failed", 502, "a service this depends on failed"
    UNAVAILABLE = "unavailable", 503, "not available on this server right now"
    UPSTREAM_TIMEOUT = "upstream_timeout", 504, "a service this depends on did not answer"

    @classmethod
    def for_status(cls, status: int) -> Code:
        """The code of an HTTP status; an unlisted one falls back to its class (4xx, 5xx)."""
        for code in cls:
            if code.status == status:
                return code
        return cls.BAD_REQUEST if status < 500 else cls.INTERNAL


class Reason(str, Enum):
    """Custom error reasons of this API, each bound to the universal code it fails with."""

    def __new__(cls, value: str, code: Code) -> Reason:
        member = str.__new__(cls, value)
        member._value_ = value
        member.code = code
        return member

    # who may call
    ORIGIN_DENIED = "origin_denied", Code.FORBIDDEN
    OPERATOR_REQUIRED = "operator_required", Code.FORBIDDEN
    OPERATOR_KEY_UNKNOWN = "operator_key_unknown", Code.UNAUTHENTICATED
    OPERATORS_UNCONFIGURED = "operators_unconfigured", Code.UNAVAILABLE
    # how often and how much
    TOO_MANY_REQUESTS = "too_many_requests", Code.RATE_LIMITED
    DAILY_BUDGET_SPENT = "daily_budget_spent", Code.RATE_LIMITED
    BODY_TOO_LARGE = "body_too_large", Code.PAYLOAD_TOO_LARGE
    BAD_CONTENT_LENGTH = "bad_content_length", Code.BAD_REQUEST
    # the factory
    COMMAND_REFUSED = "command_refused", Code.BAD_REQUEST
    INCIDENT_NOT_FOUND = "incident_not_found", Code.NOT_FOUND
    NODE_NOT_FOUND = "node_not_found", Code.NOT_FOUND
    NODE_WRITE_REFUSED = "node_write_refused", Code.BAD_REQUEST
    SUBMODEL_NOT_FOUND = "submodel_not_found", Code.NOT_FOUND
    RECORD_NOT_STORED = "record_not_stored", Code.INTERNAL
    # guarded actions
    ACTIONS_OFF = "actions_off", Code.UNAVAILABLE
    PROPOSAL_NOT_FOUND = "proposal_not_found", Code.NOT_FOUND
    # the copilot
    SESSION_NOT_FOUND = "session_not_found", Code.NOT_FOUND
    QUALITY_NOT_FOUND = "quality_not_found", Code.NOT_FOUND
    COPILOT_FAILED = "copilot_failed", Code.INTERNAL
    MODELS_BUSY = "models_busy", Code.UNAVAILABLE
    MODEL_FAILED = "model_failed", Code.UPSTREAM_FAILED
    CLOUD_TOKEN_MISSING = "cloud_token_missing", Code.UNAVAILABLE
    # voice
    NOTHING_TO_SAY = "nothing_to_say", Code.BAD_REQUEST
    VOICE_UNAVAILABLE = "voice_unavailable", Code.UNAVAILABLE
    TRANSCRIBER_UNAVAILABLE = "transcriber_unavailable", Code.UNAVAILABLE
    TRANSCRIBER_FAILED = "transcriber_failed", Code.UPSTREAM_FAILED
    TRANSCRIBER_TIMEOUT = "transcriber_timeout", Code.UPSTREAM_TIMEOUT
    AUDIO_TYPE_UNSUPPORTED = "audio_type_unsupported", Code.UNSUPPORTED_MEDIA_TYPE
    # vision
    CAPTURE_OFF = "capture_off", Code.UNAVAILABLE
    PHOTO_NOT_FOUND = "photo_not_found", Code.NOT_FOUND
    PHOTO_INVALID = "photo_invalid", Code.BAD_REQUEST
    PHOTO_TYPE_UNSUPPORTED = "photo_type_unsupported", Code.UNSUPPORTED_MEDIA_TYPE
    # guests and notices
    VISITS_UNREACHABLE = "visits_unreachable", Code.UNAVAILABLE
    NOTIFY_REFUSED = "notify_refused", Code.CONFLICT
    NOTIFY_FAILED = "notify_failed", Code.UPSTREAM_FAILED


class AppError(HTTPException):
    """A request that fails with a known code. An HTTPException, so FastAPI dependencies and
    existing `except HTTPException` blocks treat it as one."""

    def __init__(
        self,
        reason: Reason | Code,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        code = reason if isinstance(reason, Code) else reason.code
        super().__init__(status_code=code.status, detail=message or code.message, headers=headers)
        self.code = code
        self.reason = None if isinstance(reason, Code) else reason
        self.extra = extra

    @property
    def message(self) -> str:
        return str(self.detail)


class ServiceError(Exception):
    """Base of the exceptions raised inside the service. `code`/`reason` say how a request
    fails if one reaches the handlers; the message must be safe to show."""

    code: Code = Code.INTERNAL
    reason: Reason | None = None


def error_body(
    code: Code, message: str | None = None, reason: Reason | None = None, **extra: Any
) -> dict[str, Any]:
    """The JSON error body (see the module docstring)."""
    text = message or code.message
    body: dict[str, Any] = {"code": code.value, "status": code.status, "message": text}
    if reason is not None:
        body["reason"] = reason.value
    rid = request_id()
    if rid:
        body["request_id"] = rid
    body.update(extra)
    body["error"] = body["detail"] = text
    return body


def error_response(
    code: Code,
    message: str | None = None,
    reason: Reason | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    return JSONResponse(
        status_code=code.status,
        content=error_body(code, message, reason, **extra),
        headers=headers,
    )


def is_known(exc: BaseException) -> bool:
    """Does the exception carry its own code (and a message safe to show)?"""
    return isinstance(exc, (StarletteHTTPException, ServiceError))


def body_of(
    exc: BaseException, reason: Reason | None = None, message: str | None = None
) -> dict[str, Any]:
    """The error body for any exception, for streams and sockets that cannot answer with an
    HTTP status: the exception's own code where it has one; otherwise `reason` and `message`,
    or `internal`. An unknown exception's text is never shown."""
    if isinstance(exc, AppError):
        return error_body(exc.code, exc.message, exc.reason, **exc.extra)
    if isinstance(exc, StarletteHTTPException):
        text = exc.detail if isinstance(exc.detail, str) else None
        return error_body(Code.for_status(exc.status_code), text)
    if isinstance(exc, ServiceError):
        return error_body(exc.code, str(exc) or None, exc.reason)
    return error_body(reason.code if reason else Code.INTERNAL, message, reason)


def _where(request: Request) -> str:
    return f"{request.method} {request.url.path}"


async def _on_app_error(request: Request, exc: AppError) -> JSONResponse:
    level = logger.error if exc.code.status >= 500 else logger.info
    label = (exc.reason or exc.code).value
    level("%s -> %d %s: %s", _where(request), exc.code.status, label, exc.message)
    return error_response(exc.code, exc.message, exc.reason, exc.headers, **exc.extra)


async def _on_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = Code.for_status(exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else None
    level = logger.error if exc.status_code >= 500 else logger.info
    level("%s -> %d: %s", _where(request), exc.status_code, message)
    body = error_body(code, message)
    body["status"] = exc.status_code  # an unlisted status keeps its own number
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [
        {"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg", "")}
        for e in exc.errors()
    ]
    first = fields[0] if fields else None
    message = f"{first['field']}: {first['message']}" if first else Code.VALIDATION_FAILED.message
    logger.info("%s -> 422: %s", _where(request), message)
    return error_response(Code.VALIDATION_FAILED, message, fields=fields)


async def _on_service_error(request: Request, exc: ServiceError) -> JSONResponse:
    logger.error("%s -> %s: %s", _where(request), (exc.reason or exc.code).value, exc, exc_info=exc)
    return error_response(exc.code, str(exc) or None, exc.reason)


async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception processing %s: %s", _where(request), exc, exc_info=exc)
    return error_response(Code.INTERNAL)


def install(app: FastAPI) -> None:
    """Answer every failure of `app` with `error_body`."""
    app.add_exception_handler(AppError, _on_app_error)
    app.add_exception_handler(StarletteHTTPException, _on_http_error)
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    app.add_exception_handler(ServiceError, _on_service_error)
    app.add_exception_handler(Exception, _on_unhandled)
