"""Domain errors and problem+json (RFC 9457) handlers. See docs/TECHNICAL_SPEC.md section 10."""

import re
from contextlib import suppress
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"
_log = structlog.get_logger()


def _slug(name: str) -> str:
    base = name.removesuffix("Error")
    return re.sub(r"(?<!^)(?=[A-Z])", "-", base).lower()


class DomainError(Exception):
    status = 400
    title = "Request could not be completed"
    headers: dict[str, str] = {}  # noqa: RUF012 - read-only class default, never mutated

    def __init__(
        self,
        detail: str = "",
        *,
        rule_id: str | None = None,
        source_id: str | None = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.rule_id = rule_id
        self.source_id = source_id
        self.errors = errors

    @classmethod
    def type_slug(cls) -> str:
        return _slug(cls.__name__)


class RuleBlockedError(DomainError):
    status = 409
    title = "A rule blocks this action"


class StaleVersionError(DomainError):
    status = 409
    title = "The record changed since you loaded it"


class NotPermittedError(DomainError):
    status = 403
    title = "You do not have permission for this action"


class NotConfiguredError(DomainError):
    """A needed integration is not configured in this environment (503)."""

    status = 503
    title = "This feature is not configured"


class AuthAdminError(DomainError):
    """The identity provider failed or was unreachable (502). Never carries secrets."""

    status = 502
    title = "The sign-in service could not complete the request"


class InvalidRequestError(DomainError):
    """The request is well formed but cannot be applied (422)."""

    status = 422
    title = "The request cannot be applied"


class StorageError(DomainError):
    """The file store failed or was unreachable (502). Never carries secrets or file contents."""

    status = 502
    title = "The file store could not complete the request"


class PayloadTooLargeError(DomainError):
    status = 413
    title = "The file is too large"


class UnsupportedMediaError(DomainError):
    status = 415
    title = "This kind of file is not accepted"


class TooManyRequestsError(DomainError):
    """The caller has too many of this kind of request in flight (429)."""

    status = 429
    title = "Too many requests in progress"
    headers = {"Retry-After": "5"}  # noqa: RUF012


class IdempotencyConflictError(DomainError):
    """The same file or Idempotency-Key was already used with different details (409)."""

    status = 409
    title = "This was already received with different details"


class ReasonRequiredError(DomainError):
    """The change needs a non-empty reason (422)."""

    status = 422
    title = "A reason is required for this change"


class AuthenticationError(DomainError):
    """No valid credentials (401)."""

    status = 401
    title = "Authentication is required"
    headers = {"WWW-Authenticate": "Bearer"}  # noqa: RUF012


class MfaRequiredError(DomainError):
    """The role needs a token from a session that passed MFA (aal2)."""

    status = 403
    title = "Multi-factor authentication is required for this role"


class RecentAuthRequiredError(DomainError):
    """A sensitive action needs a recent login."""

    status = 403
    title = "Please sign in again to confirm this action"


class PreconditionRequiredError(DomainError):
    """If-Match is missing or unusable (RFC 6585 428)."""

    status = 428
    title = "An If-Match header with the row version is required"


class TenantMismatchError(DomainError):
    # 404, not 403: never confirm that another tenant's row exists.
    status = 404
    title = "Not found"


class SourceNotActiveError(DomainError):
    status = 409
    title = "The regulatory source is not in force for this date"


def _problem(
    request: Request,
    *,
    type_base: str,
    slug: str,
    title: str,
    status: int,
    detail: str = "",
    rule_id: str | None = None,
    source_id: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{type_base}{slug}",
        "title": title,
        "status": status,
        "instance": request.url.path,
    }
    if detail:
        body["detail"] = detail
    if rule_id:
        body["rule_id"] = rule_id
    if source_id:
        body["source_id"] = source_id
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def install_error_handlers(app: FastAPI, *, type_base: str) -> None:
    async def domain_handler(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, DomainError):
            raise exc
        return _problem(
            request,
            type_base=type_base,
            slug=exc.type_slug(),
            title=exc.title,
            status=exc.status,
            detail="" if isinstance(exc, TenantMismatchError) else exc.detail,
            rule_id=exc.rule_id,
            source_id=exc.source_id,
            errors=exc.errors,
            headers=exc.headers or None,
        )

    async def validation_handler(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, RequestValidationError):
            raise exc
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return _problem(
            request,
            type_base=type_base,
            slug="validation-error",
            title="The request is not valid",
            status=422,
            errors=errors,
        )

    async def http_handler(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, StarletteHTTPException):
            raise exc
        return _problem(
            request,
            type_base=type_base,
            slug=f"http-{exc.status_code}",
            title=str(exc.detail),
            status=exc.status_code,
        )

    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # A logging failure must never break the error response.
        with suppress(Exception):
            _log.error("unhandled_error", error_type=type(exc).__name__, path=request.url.path)
        return _problem(
            request,
            type_base=type_base,
            slug="internal-error",
            title="Something went wrong",
            status=500,
        )

    app.add_exception_handler(DomainError, domain_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_handler)
    app.add_exception_handler(Exception, unhandled_handler)
