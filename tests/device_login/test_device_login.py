import json
import os
import re
import stat

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from community_base.api.models import APIKey
from community_base.device_login import codes, rate_limit
from community_base.device_login.client import DeviceLoginError, device_login
from community_base.device_login.models import DeviceGrant, DeviceGrantStatus
from community_base.device_login.storage import read_private_json, save_private_json


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin_user(db):
    return get_user_model().objects.create_user(email="admin@example.com", is_staff=True)


@pytest.fixture
def plain_user(db):
    return get_user_model().objects.create_user(email="member@example.com")


def start_grant(client, label="agent@box", ip="10.0.0.1"):
    response = client.post(
        "/api/auth/device",
        data=json.dumps({"label": label}),
        content_type="application/json",
        REMOTE_ADDR=ip,
    )
    assert response.status_code == 200
    return response.json()


def poll(client, device_code, ip="10.0.0.2"):
    grant = DeviceGrant.objects.filter(device_code_hash=codes.sha256_hex(device_code)).first()
    if grant is not None:
        DeviceGrant.objects.filter(pk=grant.pk).update(last_poll_at=None)
    response = client.post(
        "/api/auth/device/token",
        data=json.dumps({"device_code": device_code}),
        content_type="application/json",
        REMOTE_ADDR=ip,
    )
    return response


def approve(client, user_code, approve=True):
    return client.post(
        "/api/auth/device/approve",
        data=json.dumps({"user_code": user_code, "approve": approve}),
        content_type="application/json",
    )


def test_user_code_format_and_normalization():
    seen = {codes.generate_user_code() for _ in range(50)}
    assert len(seen) > 1
    for code in seen:
        assert re.fullmatch(
            r"[BCDFGHJKLMNPQRSTVWXZ23456789]{4}-[BCDFGHJKLMNPQRSTVWXZ23456789]{4}",
            code,
        )
        assert "A" not in code and "E" not in code and "U" not in code
    assert codes.normalize_user_code("abcd-efgh") is None
    assert codes.normalize_user_code("  bcdf-ghj k  ") == "BCDFGHJK"
    assert codes.normalize_user_code("BCDF-GHJKLMNP") is None
    assert codes.normalize_user_code("") is None


def test_start_returns_offer_and_stores_hashes_only(db):
    offer = start_grant(Client())
    assert set(offer) >= {
        "device_code",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    }
    assert offer["device_code"].startswith("cbdl_")
    assert offer["verification_uri"].endswith("/device")
    assert offer["verification_uri_complete"].endswith(f"?code={offer['user_code']}")
    grant = DeviceGrant.objects.get()
    assert offer["device_code"] not in grant.device_code_hash
    assert offer["user_code"].replace("-", "") not in grant.user_code_hash
    assert grant.device_code_hash == codes.sha256_hex(offer["device_code"])
    assert grant.label == "agent@box"
    assert grant.request_ip == "10.0.0.1"


def test_start_sanitizes_label(db):
    start_grant(Client(), label="  ")
    assert DeviceGrant.objects.get().label == "CLI"
    long_label = "x" * 200
    start_grant(Client(), label=long_label, ip="10.0.0.9")
    assert len(DeviceGrant.objects.get(label__startswith="x").label) == 80


def test_token_pending_until_approved(db, admin_user):
    client = Client()
    offer = start_grant(client)
    response = poll(client, offer["device_code"])
    assert response.status_code == 400
    assert response.json()["error"] == "authorization_pending"


def test_happy_path_mints_single_use_credential(db, admin_user):
    client = Client()
    offer = start_grant(client)
    browser = Client()
    browser.force_login(admin_user)
    response = approve(browser, offer["user_code"])
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    token_response = poll(client, offer["device_code"])
    assert token_response.status_code == 200
    credential = token_response.json()
    assert credential["token"].startswith("cb_staff_")
    assert APIKey.authenticate(credential["token"]) is not None

    again = poll(client, offer["device_code"])
    assert again.status_code == 400
    assert again.json()["error"] == "expired_token"


def test_deny_reports_access_denied_once(db, admin_user):
    client = Client()
    offer = start_grant(client)
    browser = Client()
    browser.force_login(admin_user)
    assert approve(browser, offer["user_code"], approve=False).status_code == 200
    denied = poll(client, offer["device_code"])
    assert denied.status_code == 400
    assert denied.json()["error"] == "access_denied"
    gone = poll(client, offer["device_code"])
    assert gone.json()["error"] == "expired_token"


def test_expired_grant_reads_as_expired(db):
    client = Client()
    offer = start_grant(client)
    DeviceGrant.objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))
    response = poll(client, offer["device_code"])
    assert response.status_code == 400
    assert response.json()["error"] == "expired_token"


def test_unknown_device_code_is_expired(db):
    response = Client().post(
        "/api/auth/device/token",
        data=json.dumps({"device_code": "cbdl_unknown"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "expired_token"


def test_non_admin_approval_is_refused_and_mints_nothing(db, plain_user, admin_user):
    client = Client()
    offer = start_grant(client)
    browser = Client()
    browser.force_login(plain_user)
    refused = approve(browser, offer["user_code"])
    assert refused.status_code == 403
    assert refused.json()["error"] == "admin_only"
    grant = DeviceGrant.objects.get()
    assert grant.status == DeviceGrantStatus.PENDING

    pending = poll(client, offer["device_code"])
    assert pending.json()["error"] == "authorization_pending"

    admin_browser = Client()
    admin_browser.force_login(admin_user)
    assert approve(admin_browser, offer["user_code"]).status_code == 200
    assert poll(client, offer["device_code"]).status_code == 200


def test_non_admin_page_shows_refusal(db, plain_user):
    offer = start_grant(Client())
    browser = Client()
    browser.force_login(plain_user)
    response = browser.post("/device", {"action": "lookup", "user_code": offer["user_code"]})
    assert response.status_code == 200
    assert b"Only admins can approve" in response.content


def test_downgraded_admin_cannot_mint_at_poll_time(db, admin_user):
    client = Client()
    offer = start_grant(client)
    browser = Client()
    browser.force_login(admin_user)
    assert approve(browser, offer["user_code"]).status_code == 200
    admin_user.is_staff = False
    admin_user.is_superuser = False
    admin_user.save(update_fields=("is_staff", "is_superuser"))
    response = poll(client, offer["device_code"])
    assert response.status_code == 400
    assert response.json()["error"] == "access_denied"


def test_attempt_budget_kills_grant(db, admin_user):
    browser = Client()
    browser.force_login(admin_user)
    offer = start_grant(Client())
    for _ in range(rate_limit_budget_plus_one()):
        response = browser.get("/api/auth/device/pending", {"user_code": offer["user_code"]})
    assert response.status_code == 404
    assert DeviceGrant.objects.count() == 0


def rate_limit_budget_plus_one():
    from community_base.device_login.views import ATTEMPT_BUDGET

    return ATTEMPT_BUDGET + 1


def test_pending_returns_facts(db, admin_user):
    browser = Client()
    browser.force_login(admin_user)
    offer = start_grant(Client())
    response = browser.get("/api/auth/device/pending", {"user_code": offer["user_code"]})
    assert response.status_code == 200
    facts = response.json()
    assert facts["label"] == "agent@box"
    assert facts["request_ip"] == "10.0.0.1"
    assert "expires_at" in facts and "server_now" in facts


def test_pending_requires_session(db):
    offer = start_grant(Client())
    response = Client().get("/api/auth/device/pending", {"user_code": offer["user_code"]})
    assert response.status_code == 401


def test_fast_poll_returns_slow_down(db):
    client = Client()
    offer = start_grant(client, ip="10.0.0.21")
    first = client.post(
        "/api/auth/device/token",
        data=json.dumps({"device_code": offer["device_code"]}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.22",
    )
    assert first.json()["error"] == "authorization_pending"
    second = client.post(
        "/api/auth/device/token",
        data=json.dumps({"device_code": offer["device_code"]}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.22",
    )
    assert second.json()["error"] == "slow_down"


def test_start_rate_limit(db):
    client = Client()
    for index in range(rate_limit.START_LIMIT):
        response = client.post(
            "/api/auth/device",
            data=json.dumps({}),
            content_type="application/json",
            REMOTE_ADDR="10.9.9.9",
        )
        assert response.status_code == 200, index
    limited = client.post(
        "/api/auth/device",
        data=json.dumps({}),
        content_type="application/json",
        REMOTE_ADDR="10.9.9.9",
    )
    assert limited.status_code == 429
    assert limited.json()["error"] == "slow_down"


def test_device_page_requires_login(db):
    response = Client().get("/device")
    assert response.status_code == 302
    assert "next=" in response["Location"]


def test_device_page_full_flow(db, admin_user):
    offer = start_grant(Client())
    browser = Client()
    browser.force_login(admin_user)
    lookup = browser.post("/device", {"action": "lookup", "user_code": offer["user_code"]})
    assert lookup.status_code == 200
    assert b"Authorize this machine?" in lookup.content
    decide = browser.post(
        "/device",
        {"action": "decide", "user_code": offer["user_code"], "decision": "approve"},
    )
    assert b"Sign-in approved" in decide.content
    credential = poll(Client(), offer["device_code"]).json()
    assert credential["token"].startswith("cb_staff_")


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.posts = []

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return self.script.pop(0)


def test_client_loop_happy_path():
    offer = {
        "device_code": "cbdl_x",
        "user_code": "BCDF-GHJK",
        "verification_uri": "https://example.com/device/",
        "verification_uri_complete": "https://example.com/device/?code=BCDF-GHJK",
        "expires_in": 600,
        "interval": 0.01,
    }
    printed = []
    session = FakeSession(
        [
            FakeResponse(200, offer),
            FakeResponse(400, {"error": "authorization_pending"}),
            FakeResponse(200, {"token": "cb_staff_secret"}),
        ]
    )
    credential = device_login(
        "https://example.com",
        label="agent@box",
        timeout=30,
        printer=printed.append,
        session=session,
    )
    assert credential == {"token": "cb_staff_secret"}
    assert any("BCDF-GHJK" in line for line in printed)
    assert any("https://example.com/device/?code=BCDF-GHJK" in line for line in printed)
    assert not any("cbdl_x" in line for line in printed)


def test_client_loop_denied_and_expired():
    offer = {
        "device_code": "cbdl_x",
        "user_code": "BCDF-GHJK",
        "verification_uri": "https://example.com/device/",
        "expires_in": 600,
        "interval": 0.01,
    }
    with pytest.raises(DeviceLoginError) as denied:
        device_login(
            "https://example.com",
            printer=lambda line: None,
            session=FakeSession(
                [FakeResponse(200, offer), FakeResponse(400, {"error": "access_denied"})]
            ),
        )
    assert denied.value.code == "access_denied"
    with pytest.raises(DeviceLoginError) as expired:
        device_login(
            "https://example.com",
            printer=lambda line: None,
            session=FakeSession(
                [FakeResponse(200, offer), FakeResponse(400, {"error": "expired_token"})]
            ),
        )
    assert expired.value.code == "expired_token"


def test_storage_writes_private_file(tmp_path):
    target = tmp_path / "sub" / "credentials.json"
    save_private_json(target, {"token": "secret"})
    assert read_private_json(target) == {"token": "secret"}
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(target.parent).st_mode) == 0o700
