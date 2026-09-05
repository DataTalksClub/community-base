from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured, ValidationError

from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.registry import json_response
from community_base.api.safety import parse_pagination, read_json_object
from community_base.config import service
from community_base.config.registry import definition, definitions

SETTING_SCHEMA = {
    "type": "object",
    "required": ["key", "group", "value_type", "value", "source", "configured"],
}
SETTINGS_SCHEMA = {"type": "object", "properties": {"settings": {"type": "array"}}}


def _not_found(key: str) -> APIError:
    return APIError(404, "setting_not_found", "Configuration key is not declared.", {"key": key})


def _validated_definition(key: str):
    try:
        return definition(key)
    except ImproperlyConfigured as error:
        raise _not_found(key) from error


def _validation_error(error: ValidationError) -> APIError:
    return APIError(
        422,
        "validation_error",
        "Configuration value is invalid.",
        {"messages": error.messages},
    )


@route("GET", "settings", "settings.read", "List runtime settings", SETTINGS_SCHEMA)
def list_settings(request):
    page = parse_pagination(request)
    declared = definitions()
    selected = declared[page.offset : page.offset + page.limit]
    return json_response(
        {
            "settings": [service.describe(item.key) for item in selected],
            "pagination": {
                "limit": page.limit,
                "offset": page.offset,
                "total": len(declared),
            },
        }
    )


@route(
    "GET",
    "settings/export",
    "settings.read",
    "Export runtime settings",
    {"type": "object"},
)
def export_settings(request):
    return json_response({"settings": service.export()})


@route(
    "POST",
    "settings/import",
    "settings.write",
    "Import runtime settings",
    {"type": "object"},
    {"type": "object", "required": ["settings"]},
)
def import_settings(request):
    payload = read_json_object(request)
    values = payload.get("settings")
    if not isinstance(values, dict):
        raise APIError(422, "validation_error", "settings must be an object.")
    try:
        rows = service.import_(
            values,
            actor_ref=f"api-key:{request.api_key.pk}",
            reason=str(payload.get("reason", "Imported through API")),
        )
    except ValidationError as error:
        raise _validation_error(error) from error
    except ImproperlyConfigured as error:
        raise APIError(422, "validation_error", str(error)) from error
    return json_response({"updated": [row.key for row in rows]})


@route(
    "GET",
    "settings/<str:key>",
    "settings.read",
    "Read a runtime setting",
    SETTING_SCHEMA,
)
def get_setting(request, key):
    _validated_definition(key)
    return json_response(service.describe(key))


@route(
    "PUT",
    "settings/<str:key>",
    "settings.write",
    "Update a runtime setting",
    SETTING_SCHEMA,
    {"type": "object", "required": ["value"]},
)
def put_setting(request, key):
    _validated_definition(key)
    payload = read_json_object(request)
    if "value" not in payload:
        raise APIError(422, "validation_error", "value is required.")
    try:
        service.set(
            key,
            payload["value"],
            actor_ref=f"api-key:{request.api_key.pk}",
            reason=str(payload.get("reason", "Updated through API")),
            source="api",
        )
    except ValidationError as error:
        raise _validation_error(error) from error
    return json_response(service.describe(key))
