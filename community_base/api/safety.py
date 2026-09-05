from __future__ import annotations

import json
from dataclasses import dataclass

from community_base.api.errors import APIError

DEFAULT_BODY_LIMIT = 1_048_576
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class Pagination:
    limit: int
    offset: int


def read_json_object(request, *, max_bytes: int = DEFAULT_BODY_LIMIT) -> dict:
    content_length = request.META.get("CONTENT_LENGTH")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise APIError(413, "body_too_large", "Request body is too large.")
        except ValueError as error:
            raise APIError(400, "invalid_content_length", "Content-Length is invalid.") from error
    if len(request.body) > max_bytes:
        raise APIError(413, "body_too_large", "Request body is too large.")
    try:
        value = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise APIError(400, "invalid_json", "Request body is not valid JSON.") from error
    if not isinstance(value, dict):
        raise APIError(
            400,
            "invalid_type",
            "Request body must be a JSON object.",
            details={"field": "body", "expected": "object"},
        )
    return value


def parse_pagination(request) -> Pagination:
    try:
        limit = int(request.GET.get("limit", DEFAULT_PAGE_LIMIT))
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError) as error:
        raise APIError(400, "invalid_pagination", "Pagination values must be integers.") from error
    if not 1 <= limit <= MAX_PAGE_LIMIT or offset < 0:
        raise APIError(
            400,
            "invalid_pagination",
            "Pagination values are outside the allowed range.",
            details={"limit_max": MAX_PAGE_LIMIT, "offset_min": 0},
        )
    return Pagination(limit=limit, offset=offset)


def refuse_delete(*, resource: str) -> None:
    raise APIError(
        405,
        f"{resource}_delete_not_available",
        f"{resource.replace('_', ' ').title()} deletion is not available through the API.",
    )
