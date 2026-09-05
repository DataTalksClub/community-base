from __future__ import annotations

from unittest import mock

import pytest

from community_base.mail import relay_links
from community_base.mail.relay_links import BridgeOutcome
from community_base.testing import FakeRelay, unreachable_relay

RELAY = "http://relay.website.internal:8000"
TOKEN = "kD3Yy8x-Ug2f_QwErTyUiOpAsDfGhJkLzXcVbNm1234"


@pytest.fixture(autouse=True)
def configured_relay(settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "RELAY_BASE_URL": RELAY}
    relay_links.reset_pool()
    yield
    relay_links.reset_pool()


def run_with(relay, callback, *args):
    with mock.patch.object(relay_links, "_pool", return_value=relay):
        return callback(*args)


def test_token_destination_and_fingerprint_rules():
    assert relay_links.is_well_formed_token(TOKEN)
    assert relay_links.is_safe_click_destination("https://example.com/a?b=c")
    assert not relay_links.is_well_formed_token("../secret")
    assert not relay_links.is_safe_click_destination("javascript:alert(1)")
    fingerprint = relay_links.token_fingerprint(TOKEN)
    assert len(fingerprint) == 12
    assert fingerprint == relay_links.token_fingerprint(TOKEN)
    assert fingerprint not in TOKEN


def test_bridge_forwards_relays_exact_contract():
    relay = FakeRelay(status_code=200)
    assert run_with(relay, relay_links.record_open, TOKEN).outcome is BridgeOutcome.RECORDED
    assert relay.calls[0].url == f"{RELAY}/t/o/{TOKEN}.gif"
    assert relay.calls[0].allow_redirects is False

    relay = FakeRelay(status_code=302)
    destination = "https://example.com/post?a=1"
    assert (
        run_with(relay, relay_links.record_click, TOKEN, destination).outcome
        is BridgeOutcome.RECORDED
    )
    assert relay.calls[0].url == f"{RELAY}/t/c/{TOKEN}"
    assert relay.calls[0].params == {"u": destination}

    relay = FakeRelay(status_code=200)
    run_with(relay, relay_links.submit_unsubscribe, TOKEN, "client")
    assert relay.calls[0].url == f"{RELAY}/unsubscribe/{TOKEN}"
    assert relay.calls[0].data == {"scope": "client"}


def test_endpoint_latency_budgets_are_bounded_by_route():
    budgets = []
    for callback, args in (
        (relay_links.record_open, (TOKEN,)),
        (relay_links.record_click, (TOKEN, "https://example.com/")),
        (relay_links.submit_unsubscribe, (TOKEN, "client")),
    ):
        relay = FakeRelay()
        run_with(relay, callback, *args)
        budgets.append(relay.calls[0].timeout)
    assert budgets[0] < budgets[2]
    assert budgets[1] < budgets[2]


def test_malformed_input_never_opens_a_socket():
    relay = FakeRelay()
    assert run_with(relay, relay_links.record_open, "short").outcome is BridgeOutcome.REJECTED
    assert (
        run_with(relay, relay_links.record_click, TOKEN, "javascript:alert(1)").outcome
        is BridgeOutcome.INVALID
    )
    assert not relay.called


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, BridgeOutcome.RECORDED),
        (302, BridgeOutcome.RECORDED),
        (400, BridgeOutcome.INVALID),
        (404, BridgeOutcome.REJECTED),
        (401, BridgeOutcome.UNAVAILABLE),
        (503, BridgeOutcome.UNAVAILABLE),
    ],
)
def test_relay_status_codes_map_to_safe_outcomes(status, outcome):
    assert run_with(FakeRelay(status), relay_links.record_open, TOKEN).outcome is outcome


def test_transport_failure_is_swallowed():
    assert (
        run_with(unreachable_relay(), relay_links.record_open, TOKEN).outcome
        is BridgeOutcome.UNAVAILABLE
    )


def test_unconfigured_or_invalid_base_fails_closed(settings):
    for value in ("", "relay.internal", "ftp://relay/", "http:///", "http://r/?x=1"):
        settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "RELAY_BASE_URL": value}
        assert not relay_links.is_configured()
    assert (
        relay_links.record_click(TOKEN, "https://example.com").outcome
        is BridgeOutcome.NOT_CONFIGURED
    )


def test_trailing_slash_does_not_double_the_path_separator(settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "RELAY_BASE_URL": f"{RELAY}/"}
    assert relay_links.bridge_base_url() == RELAY


def test_unknown_unsubscribe_token_maps_to_rejected():
    result = run_with(FakeRelay(404), relay_links.load_unsubscribe, TOKEN)
    assert result.outcome is BridgeOutcome.REJECTED


def test_all_bridge_calls_disable_redirect_following():
    relay = FakeRelay(200)
    run_with(relay, relay_links.load_unsubscribe, TOKEN)
    assert relay.calls[0].allow_redirects is False


def test_fingerprint_of_absent_token_is_non_identifying():
    assert relay_links.token_fingerprint("") == "absent"
