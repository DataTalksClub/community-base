from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.http import HttpRequest, JsonResponse

from community_base.kernel.redaction import redact


@dataclass(slots=True)
class APIError(Exception):
    status: int
    code: str
    message: str
    details: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


def error_response(request: HttpRequest, error: APIError) -> JsonResponse:
    payload: dict[str, Any] = {
        "error": {
            "code": error.code,
            "message": error.message,
            "details": redact(error.details or {}),
        }
    }
    response = JsonResponse(payload, status=error.status)
    for name, value in error.headers.items():
        response[name] = value
    return response


def authentication_required() -> APIError:
    return APIError(
        status=401,
        code="authentication_required",
        message="Valid Bearer authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def session_authentication_required() -> APIError:
    return APIError(
        status=401,
        code="authentication_required",
        message="An authenticated session is required.",
    )


def permission_denied() -> APIError:
    return APIError(status=403, code="permission_denied", message="Permission is denied.")


def method_not_allowed() -> APIError:
    return APIError(status=405, code="method_not_allowed", message="Method is not allowed.")
