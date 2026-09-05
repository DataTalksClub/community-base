import json

import pytest
from django.core.management import CommandError, call_command

from community_base.api.openapi import build_document


def test_openapi_contains_registered_route_and_security_scheme():
    document = build_document()

    operation = document["paths"]["/api/v1/fixtures/ping"]["get"]
    assert operation["security"] == [{"bearerAuth": []}]
    assert operation["x-required-scope"] == "fixtures.read"
    assert document["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"


def test_openapi_contains_session_self_routes_and_concurrency_headers():
    document = build_document()

    get_operation = document["paths"]["/api/v1/me/profile"]["get"]
    patch_operation = document["paths"]["/api/v1/me/profile"]["patch"]
    parameters = {parameter["name"]: parameter for parameter in patch_operation["parameters"]}

    assert get_operation["security"] == [{"cookieAuth": []}]
    assert patch_operation["security"] == [{"cookieAuth": []}]
    assert parameters["X-CSRFToken"]["required"] is True
    assert parameters["If-Match"]["schema"]["pattern"] == '^"rev-[0-9]+"$'
    assert document["components"]["securitySchemes"]["cookieAuth"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "sessionid",
    }


def test_openapi_check_detects_and_repairs_drift(tmp_path):
    output = tmp_path / "openapi.json"

    with pytest.raises(CommandError, match="stale"):
        call_command("openapi", check=True, output=output)

    call_command("openapi", output=output)
    call_command("openapi", check=True, output=output)

    assert json.loads(output.read_text())["openapi"] == "3.1.0"
