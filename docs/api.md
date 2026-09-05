# Shared API contract

The package API is JSON over HTTPS and is mounted at `/api/v1/`. Its implementation and setup are
documented in `community_base/api/README.md`.

## Authentication and scopes

Send `Authorization: Bearer <key>`. Missing, malformed, unknown and revoked credentials return 401
with `WWW-Authenticate: Bearer`. Authentication happens before method dispatch so unauthenticated
callers cannot discover allowed methods. An authenticated key without the route's exact scope
returns 403. The `*` scope is deliberately unrestricted and should be issued sparingly.

Staff and member keys share the storage and authentication mechanism. A route's scope is the
authority boundary; applications should use dotted resource/action names such as `settings.read`
and `settings.write`.

## Error envelope

Every API error has `error.code`, `error.message` and `error.details`. Codes and messages are stable
client contracts. Dynamic details are redacted. Authentication failures are 401, authorization
failures are 403, validation failures are 400 or 422, oversized bodies are 413, and disallowed
methods are 405.

## Pagination and deletion

List endpoints use non-negative `offset` and `limit` from 1 to 100. Canonical content is not
hard-deleted through the API; return a resource-specific 405. Relationship removal, soft deletion,
member-owned structure edits and guarded operator configuration may use DELETE only when the
owning domain documents and tests that classification.

## OpenAPI drift check

Each registered route declares its method, path, scope, summary, response schema and optional
request schema. Run `python manage.py openapi` to generate the OpenAPI 3.1 document and
`python manage.py openapi --check` in CI. A changed registry without a regenerated document fails.
