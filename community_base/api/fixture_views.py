from community_base.api.registry import json_response, route


@route(
    "GET",
    "fixtures/ping",
    "fixtures.read",
    "Verify scoped bearer authentication",
    {"type": "object", "properties": {"ok": {"type": "boolean"}}},
)
def ping(request):
    return json_response({"ok": True})
