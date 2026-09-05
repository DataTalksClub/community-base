from __future__ import annotations

import pytest

from community_base.mail.relay import RelayMailClient, RelayMailError
from tests.mail.fake_relay import FakeMailRelayTransport, FakeResponse


@pytest.fixture
def catalog():
    transport = FakeMailRelayTransport()
    client = RelayMailClient("https://relay.example.com", "relay-test-key", transport=transport)
    client.put_template(
        "welcome",
        {
            "name": "Welcome",
            "subject": "Hello {{ name }}",
            "body": "Hello {{ name }}",
            "required_context": ["name"],
        },
    )
    return client, transport


def test_catalog_draft_publish_and_version_listing(catalog):
    client, transport = catalog
    assert client.templates()[0]["key"] == "welcome"
    published = client.publish_template("welcome")
    assert published == {"template_key": "welcome", "version": 1, "status": "published"}
    assert client.template_versions("welcome") == (published,)
    paths = [call[1].removeprefix("https://relay.example.com") for call in transport.calls]
    assert paths == [
        "/api/transactional/templates/welcome",
        "/api/transactional/templates",
        "/api/transactional/templates/welcome/publish",
        "/api/transactional/templates/welcome/versions",
    ]


def test_catalog_preview_and_allowlisted_test_send(catalog):
    client, _ = catalog
    client.publish_template("welcome")
    rendered = client.preview_template("welcome", {"name": "Alexey"}, version=1)
    sent = client.test_send_template("welcome", "staff@example.com", {"name": "Alexey"}, version=1)
    assert rendered["subject"] == "Hello Alexey"
    assert sent.status == "queued"
    assert sent.template_version == 1


@pytest.mark.parametrize(
    ("method", "response"),
    [
        ("templates", FakeResponse(200, {"templates": "bad"})),
        ("preview", FakeResponse(200, {"rendered": {"subject": "incomplete"}})),
        ("publish", FakeResponse(201, {"version": {"version": 0}})),
    ],
)
def test_catalog_rejects_malformed_responses(catalog, method, response):
    client, transport = catalog
    transport.next_response = response
    with pytest.raises(RelayMailError):
        if method == "templates":
            client.templates()
        elif method == "preview":
            client.preview_template("welcome", {})
        else:
            client.publish_template("welcome")


def test_catalog_rejects_unsafe_template_key_before_network(catalog):
    client, transport = catalog
    prior_calls = len(transport.calls)
    with pytest.raises(ValueError, match="invalid template key"):
        client.publish_template("../secret")
    assert len(transport.calls) == prior_calls
