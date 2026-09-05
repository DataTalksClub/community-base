import math
import uuid

import pytest

from community_base.jobs.registry import (
    RegistryError,
    register_handler,
    schedule,
    validate_payload,
)


def test_payload_accepts_json_domain_identifiers():
    payload = {
        "email_delivery_id": str(uuid.uuid4()),
        "registration_ids": ["one", "two"],
        "attempt": 2,
    }
    assert validate_payload(payload) == payload


@pytest.mark.parametrize(
    "key",
    ["authorization", "access_token", "requestBody", "password_hash", "emailDeliveryId"],
)
def test_payload_rejects_protected_fields(key):
    with pytest.raises(RegistryError, match="protected field"):
        validate_payload({key: "plain-secret-canary"})


def test_payload_allows_protected_field_only_for_proven_opaque_id():
    opaque = str(uuid.uuid4())
    assert validate_payload({"emailDeliveryId": opaque}) == {"emailDeliveryId": opaque}


@pytest.mark.parametrize(
    "value",
    [
        "Bearer redaction-canary",
        "https://example.invalid/private",
        "person@example.invalid",
        "abcdefgh.ijklmnop.qrstuvwx",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
def test_payload_rejects_protected_values(value):
    with pytest.raises(RegistryError, match="protected value"):
        validate_payload({"reference": value})


def test_payload_rejects_non_finite_and_deep_values():
    with pytest.raises(RegistryError):
        validate_payload({"number": math.inf})
    deep = 1
    for key in reversed("abcdefghi"):
        deep = {key: deep}
    with pytest.raises(RegistryError):
        validate_payload(deep)


def test_handler_registration_is_idempotent_but_conflicts_fail():
    def callback(context, payload):
        del context, payload

    register_handler("tests.registry.handler")(callback)
    register_handler("tests.registry.handler")(callback)

    with pytest.raises(RegistryError, match="already registered"):

        @register_handler("tests.registry.handler")
        def other(context, payload):
            del context, payload


def test_schedule_requires_registered_handler_and_five_field_cron():
    @register_handler("tests.registry.scheduled")
    def callback(context, payload):
        del context, payload

    declared = schedule("tests.registry.scheduled", "*/5 * * * *", {"record_id": 1})
    assert declared.name == "tests.registry.scheduled"

    with pytest.raises(RegistryError, match="five fields"):
        schedule("tests.registry.scheduled", "hourly", {})
