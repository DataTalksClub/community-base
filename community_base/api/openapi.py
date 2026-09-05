from __future__ import annotations

import re

from apispec import APISpec

from community_base.api.registry import Route, routes

_CONVERTER_SCHEMAS = {
    "int": {"type": "integer"},
    "str": {"type": "string"},
    "slug": {"type": "string"},
    "uuid": {"type": "string", "format": "uuid"},
    "path": {"type": "string"},
}
_CONVERTER_RE = re.compile(r"<(?:(?P<converter>[^:>]+):)?(?P<name>[^>]+)>")


def _openapi_path(route_path: str) -> tuple[str, list[dict]]:
    parameters: list[dict] = []

    def replace(match: re.Match) -> str:
        converter = match.group("converter") or "str"
        name = match.group("name")
        parameters.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": _CONVERTER_SCHEMAS.get(converter, {"type": "string"}),
            }
        )
        return f"{{{name}}}"

    return f"/api/v1/{_CONVERTER_RE.sub(replace, route_path)}", parameters


def _operation(entry: Route, parameters: list[dict]) -> dict:
    operation = {
        "summary": entry.summary,
        "responses": {
            "200": {
                "description": "Successful response",
                "content": {"application/json": {"schema": entry.response}},
            },
            "401": {"$ref": "#/components/responses/APIError"},
            "403": {"$ref": "#/components/responses/APIError"},
        },
        "security": [{"cookieAuth": []}]
        if entry.authentication == "session"
        else [{"bearerAuth": []}],
    }
    if entry.scope:
        operation["x-required-scope"] = entry.scope
    operation_parameters = list(parameters)
    if entry.authentication == "session" and entry.method != "GET":
        operation_parameters.append(
            {
                "name": "X-CSRFToken",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
            }
        )
    if entry.requires_if_match:
        operation_parameters.append(
            {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "pattern": '^"rev-[0-9]+"$'},
            }
        )
        operation["responses"]["409"] = {"$ref": "#/components/responses/APIError"}
        operation["responses"]["428"] = {"$ref": "#/components/responses/APIError"}
    if operation_parameters:
        operation["parameters"] = operation_parameters
    if entry.request is not None:
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": entry.request}},
        }
    return operation


def build_document(*, registered_routes: tuple[Route, ...] | None = None) -> dict:
    spec = APISpec(
        title="Community Base API",
        version="1.0.0",
        openapi_version="3.1.0",
        info={"description": "Shared administration and member API."},
    )
    spec.components.security_scheme(
        "bearerAuth",
        {"type": "http", "scheme": "bearer", "bearerFormat": "API key"},
    )
    spec.components.security_scheme(
        "cookieAuth",
        {"type": "apiKey", "in": "cookie", "name": "sessionid"},
    )
    spec.components.response(
        "APIError",
        {
            "description": "Stable API error envelope",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["error"],
                        "properties": {
                            "error": {
                                "type": "object",
                                "required": ["code", "message", "details"],
                                "properties": {
                                    "code": {"type": "string"},
                                    "message": {"type": "string"},
                                    "details": {"type": "object"},
                                },
                            }
                        },
                    }
                }
            },
        },
    )
    operations_by_path: dict[str, dict] = {}
    for entry in registered_routes if registered_routes is not None else routes():
        openapi_path, parameters = _openapi_path(entry.path)
        operations_by_path.setdefault(openapi_path, {})[entry.method.lower()] = _operation(
            entry, parameters
        )
    for openapi_path, operations in operations_by_path.items():
        spec.path(path=openapi_path, operations=operations)
    return spec.to_dict()
