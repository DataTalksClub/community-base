from __future__ import annotations

from unittest import mock

import pytest
from django.urls import resolve, reverse
from django.utils.encoding import iri_to_uri

from community_base.jobs.models import JobIntent
from community_base.mail import relay_links
from community_base.mail.models import PendingUnsubscribe
from community_base.mail.relay_links import TRANSPARENT_GIF
from tests.mail.support import FakeRelay, timing_out_relay, unreachable_relay

RELAY = "http://relay.website.internal:8000"
TOKEN = "kD3Yy8x-Ug2f_QwErTyUiOpAsDfGhJkLzXcVbNm1234"
OPEN_PATH = f"/t/o/{TOKEN}.gif"
CLICK_PATH = f"/t/c/{TOKEN}"
UNSUBSCRIBE_PATH = f"/unsubscribe/{TOKEN}"


@pytest.fixture(autouse=True)
def configured_relay(settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "RELAY_BASE_URL": RELAY}


def relay(relay_client):
    return mock.patch.object(relay_links, "_pool", return_value=relay_client)


def test_routes_keep_relays_exact_names_and_shapes():
    cases = {
        OPEN_PATH: ("relay-tracking-open", {"tracking_token": TOKEN}),
        CLICK_PATH: ("relay-tracking-click", {"tracking_token": TOKEN}),
        UNSUBSCRIBE_PATH: ("relay-public-unsubscribe", {"unsubscribe_token": TOKEN}),
    }
    for path, (name, kwargs) in cases.items():
        match = resolve(path)
        assert match.url_name == name
        assert match.kwargs == kwargs
        assert reverse(name, kwargs=kwargs) == path


@pytest.mark.django_db
def test_open_pixel_always_returns_valid_private_gif(client):
    for relay_client, status in (
        (FakeRelay(200), 200),
        (FakeRelay(404), 404),
        (unreachable_relay(), 200),
        (timing_out_relay(), 200),
        (FakeRelay(503), 200),
    ):
        with relay(relay_client):
            response = client.get(OPEN_PATH)
        assert response.status_code == status
        assert response.content == TRANSPARENT_GIF
        assert "no-store" in response["Cache-Control"]
        assert response["X-Robots-Tag"] == "noindex, nofollow"
        assert "Set-Cookie" not in response.headers


@pytest.mark.django_db
def test_verified_click_redirects_but_unverified_click_never_does(client):
    with relay(FakeRelay(302)):
        response = client.get(CLICK_PATH, {"u": "https://example.com/post"})
    assert response.status_code == 302
    assert response["Location"] == "https://example.com/post"

    with relay(unreachable_relay()):
        response = client.get(CLICK_PATH, {"u": "https://example.com/post"})
    assert response.status_code == 200
    assert "Location" not in response.headers
    assert b"could not check this link" in response.content


@pytest.mark.django_db
def test_unsafe_click_destination_is_never_offered_or_forwarded(client):
    relay_client = FakeRelay(302)
    with relay(relay_client):
        response = client.get(CLICK_PATH, {"u": "javascript:alert(1)"})
    assert response.status_code == 400
    assert b"javascript:" not in response.content
    assert not relay_client.called


@pytest.mark.django_db
def test_unsubscribe_get_is_read_only_and_post_applies_choice(client):
    relay_client = FakeRelay(200)
    with relay(relay_client):
        response = client.get(UNSUBSCRIBE_PATH)
        confirmed = client.post(UNSUBSCRIBE_PATH, {"scope": "global"})
    assert response.status_code == 200
    assert b'name="scope"' in response.content
    assert not PendingUnsubscribe.objects.exists()
    assert confirmed.status_code == 200
    assert b"You have been unsubscribed" in confirmed.content
    assert relay_client.calls[-1].data == {"scope": "global"}


@pytest.mark.django_db
def test_relay_outage_makes_unsubscribe_durable(client):
    with relay(unreachable_relay()):
        response = client.post(UNSUBSCRIBE_PATH, {"scope": "client"})
    assert response.status_code == 202
    pending = PendingUnsubscribe.objects.get()
    assert pending.token_fingerprint == relay_links.token_fingerprint(TOKEN)
    job = JobIntent.objects.get(handler="cb_mail.unsubscribe_replay")
    assert job.payload == {"pending_unsubscribe_id": str(pending.id)}
    assert TOKEN not in str(job.payload)


@pytest.mark.django_db
def test_token_is_not_rendered_or_logged_by_django(client, caplog):
    with relay(FakeRelay(404)):
        response = client.get(UNSUBSCRIBE_PATH)
    assert response.status_code == 404
    assert TOKEN not in response.content.decode()
    assert TOKEN not in caplog.text


@pytest.mark.django_db
def test_unconfigured_bridge_routes_fail_closed(client, settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "RELAY_BASE_URL": ""}
    assert client.get(OPEN_PATH).status_code == 404
    click = client.get(CLICK_PATH, {"u": "https://example.com"})
    assert click.status_code == 404
    assert "Location" not in click.headers
    assert client.get(UNSUBSCRIBE_PATH).status_code == 404


@pytest.mark.django_db
def test_malformed_pixel_token_never_reaches_relay(client):
    relay_client = FakeRelay(200)
    with relay(relay_client):
        response = client.get("/t/o/short.gif")
    assert response.status_code == 404
    assert response.content == TRANSPARENT_GIF
    assert not relay_client.called


@pytest.mark.django_db
def test_duplicate_destination_cannot_split_record_from_redirect(client):
    relay_client = FakeRelay(302)
    with relay(relay_client):
        response = client.get(f"{CLICK_PATH}?u=https://example.com/one&u=https://example.com/two")
    assert response["Location"] == relay_client.calls[0].params["u"]


@pytest.mark.django_db
def test_click_destination_survives_decode_and_encode(client):
    destination = "https://example.com/a b?q=data&letter=ü"
    relay_client = FakeRelay(302)
    with relay(relay_client):
        response = client.get(CLICK_PATH, {"u": destination})
    assert relay_client.calls[0].params == {"u": destination}
    assert response["Location"] == iri_to_uri(destination)


@pytest.mark.django_db
def test_unknown_unsubscribe_link_changes_nothing(client):
    with relay(FakeRelay(404)):
        response = client.get(UNSUBSCRIBE_PATH)
    assert response.status_code == 404
    assert b"no longer valid" in response.content
    assert not PendingUnsubscribe.objects.exists()


@pytest.mark.django_db
def test_unsupported_unsubscribe_scope_never_reaches_relay(client):
    relay_client = FakeRelay(200)
    with relay(relay_client):
        response = client.post(UNSUBSCRIBE_PATH, {"scope": "everything"})
    assert response.status_code == 400
    assert b"Choose one option" in response.content
    assert not relay_client.called


@pytest.mark.django_db
def test_degraded_unsubscribe_get_still_offers_form(client):
    with relay(unreachable_relay()):
        response = client.get(UNSUBSCRIBE_PATH)
    assert response.status_code == 200
    assert b'name="scope"' in response.content
    assert b"could not check this link" in response.content


@pytest.mark.django_db
def test_unsubscribe_page_needs_no_cookie_or_csrf_token(client):
    with relay(FakeRelay(200)):
        response = client.get(UNSUBSCRIBE_PATH)
    assert "Set-Cookie" not in response.headers
    assert b"csrfmiddlewaretoken" not in response.content


@pytest.mark.django_db
def test_unsubscribe_page_is_private_and_unindexed(client):
    with relay(FakeRelay(200)):
        response = client.get(UNSUBSCRIBE_PATH)
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert response["X-Robots-Tag"] == "noindex, nofollow"
