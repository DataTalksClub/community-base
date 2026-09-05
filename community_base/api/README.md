# API app

`community_base.api` supplies the shared JSON API foundation. Install it after
`community_base.kernel`, mount `community_base.api.registry.urlpatterns()` below `/api/v1/`, and
mount `community_base.api.urls` below `/studio/` for superuser key management.

## Register a route

```python
from community_base.api import route
from community_base.api.registry import json_response


@route(
    "GET",
    "widgets/<uuid:widget_id>",
    "widgets.read",
    "Read a widget",
    {"type": "object"},
)
def widget_detail(request, widget_id):
    return json_response({"id": str(widget_id)})
```

Routes sharing a path are dispatched by method. Duplicate method/path registrations and
unsupported methods fail at import time. The decorator authenticates `Authorization: Bearer`
credentials, attaches `request.api_key` and `request.user`, and requires the declared scope. A key
with the explicit `*` scope is unrestricted.

## Keys

`APIKey` stores a Django password hash and a lookup prefix, never the credential. Staff keys require
a staff owner; member keys require an active user. Plaintext is returned only from
`APIKey.create_for_user(...)` and only the create response at `/studio/api-keys/` renders it.
Revocation is permanent. Successful use records a timestamp and a salted hash of the remote IP.

Only superusers may list, create or revoke keys in Studio. Revocation requires an explicit `revoke`
confirmation value.

## Errors and safety

Errors use this stable shape:

```json
{"error": {"code": "permission_denied", "message": "Permission is denied.", "details": {}}}
```

Dynamic details pass through package redaction. `safety.read_json_object` bounds request bodies and
requires an object. `safety.parse_pagination` accepts `limit` from 1 to 100 and a non-negative
`offset`. Canonical resources call `safety.refuse_delete(resource=...)`; a new DELETE route must be
explicitly classified as a legitimate relationship/attribute removal or as unavailable.

## OpenAPI

The registry generates OpenAPI 3.1 through `apispec`:

```text
uv run python manage.py openapi --output api/openapi.json
uv run python manage.py openapi --check --output api/openapi.json
```

Commit the generated file. CI uses `--check` so route or schema drift fails.
