import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.accounts.adapters import SocialAccountAdapter
from community_base.accounts.models import EmailAlias
from community_base.accounts.settings import allauth_settings
from community_base.accounts.tokens import generate_verification_token
from community_base.mail.backends.memory import outbox

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def clear_outbox():
    outbox.clear()
    yield
    outbox.clear()


def _token_from_message(message, key):
    return parse_qs(urlparse(message.context[key]).query)["token"][0]


def test_allauth_settings_use_email_identity_and_package_adapter():
    configured = allauth_settings()

    assert configured["ACCOUNT_LOGIN_METHODS"] == {"email"}
    assert configured["ACCOUNT_SIGNUP_FIELDS"] == ["email*"]
    assert configured["ACCOUNT_USER_MODEL_USERNAME_FIELD"] is None
    assert configured["SOCIALACCOUNT_ADAPTER"] == (
        "community_base.accounts.adapters.SocialAccountAdapter"
    )
    assert configured["SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT"] is True
    assert configured["SOCIALACCOUNT_PROVIDERS"]["github"]["SCOPE"] == ["user:email"]


def test_public_pages_render_from_package(client):
    for name, text in (
        ("accounts:login", "Sign in"),
        ("accounts:register", "Create an account"),
        ("accounts:password_reset_request", "Reset password"),
    ):
        response = client.get(reverse(name))
        assert response.status_code == 200
        assert text.encode() in response.content
        assert b'class="cb-page"' in response.content


def test_registration_queues_verification_logs_in_and_verifies(client):
    response = client.post(
        reverse("accounts:register"),
        {"email": "New@Example.com", "password": "strong-passphrase"},
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:verification_sent")
    user = get_user_model().objects.get(email="new@example.com")
    assert user.email_verified is False
    assert user.signup_source == "signup"
    assert user.verification_expires_at is not None
    assert str(user.pk) == client.session["_auth_user_id"]
    assert len(outbox) == 1
    assert outbox[0].purpose == "accounts.verify_email"

    token = _token_from_message(outbox[0], "verify_url")
    response = client.get(reverse("accounts:verify_email"), {"token": token})
    user.refresh_from_db()
    assert response.status_code == 200
    assert user.email_verified is True
    assert user.account_activated is True
    assert user.verification_expires_at is None
    assert response["Cache-Control"] == "private, no-store, max-age=0"


def test_registration_rejects_duplicate_email_case_insensitively(client):
    get_user_model().objects.create_user(email="member@example.com", password="password")

    response = client.post(
        reverse("accounts:register"),
        {"email": "MEMBER@example.com", "password": "strong-passphrase"},
    )

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert get_user_model().objects.count() == 1
    assert outbox == []


def test_verification_does_not_redirect_to_external_return(client):
    user = get_user_model().objects.create_user(email="member@example.com", password="password")
    token = generate_verification_token(user, return_path="https://example.net/stolen")

    response = client.get(reverse("accounts:verify_email"), {"token": token})

    assert response.status_code == 200
    assert b"Your email address is verified" in response.content


def test_registration_preserves_safe_verification_return(client):
    client.post(
        reverse("accounts:register"),
        {
            "email": "return@example.com",
            "password": "strong-passphrase",
            "next": "/events/42/",
        },
    )
    token = _token_from_message(outbox[0], "verify_url")

    response = client.get(reverse("accounts:verify_email"), {"token": token})

    assert response.status_code == 302
    assert response.url == "/events/42/"


def test_login_accepts_primary_email_and_safe_next(client):
    user = get_user_model().objects.create_user(email="member@example.com", password="password")

    response = client.post(
        reverse("accounts:login") + "?next=/events/",
        {"email": "MEMBER@example.com", "password": "password", "next": "/events/"},
    )

    assert response.status_code == 302
    assert response.url == "/events/"
    assert str(user.pk) == client.session["_auth_user_id"]


def test_login_accepts_alias_but_never_inactive_primary(client):
    canonical = get_user_model().objects.create_user(
        email="primary@example.com", password="password"
    )
    EmailAlias.objects.create(user=canonical, email="old@example.com", source="merge")
    get_user_model().objects.create_user(
        email="disabled@example.com", password="password", is_active=False
    )

    alias_response = client.post(
        reverse("accounts:login"),
        {"email": "old@example.com", "password": "password"},
    )
    client.post(reverse("accounts:logout"))
    disabled_response = client.post(
        reverse("accounts:login"),
        {"email": "disabled@example.com", "password": "password"},
    )

    assert alias_response.status_code == 302
    assert disabled_response.status_code == 200
    assert b"Invalid email or password" in disabled_response.content


def test_password_reset_is_non_enumerating_and_completes(client):
    user = get_user_model().objects.create_user(email="member@example.com", password="old-password")

    missing = client.post(
        reverse("accounts:password_reset_request"), {"email": "absent@example.com"}
    )
    existing = client.post(
        reverse("accounts:password_reset_request"), {"email": "member@example.com"}
    )

    assert missing.status_code == existing.status_code == 200
    assert missing.content == existing.content
    assert len(outbox) == 1
    token = _token_from_message(outbox[0], "reset_url")

    form = client.get(reverse("accounts:password_reset"), {"token": token})
    completed = client.post(
        reverse("accounts:password_reset"),
        {"token": token, "new_password": "new-strong-password"},
    )
    user.refresh_from_db()
    replay = client.get(reverse("accounts:password_reset"), {"token": token})

    assert form.status_code == 200
    assert completed.status_code == 302
    assert completed.url == reverse("accounts:password_reset_complete")
    assert user.check_password("new-strong-password")
    assert user.account_activated is True
    assert replay.status_code == 400


def test_api_registration_login_resend_and_reset(client):
    register = client.post(
        "/api/register",
        data=json.dumps({"email": "api@example.com", "password": "api-password"}),
        content_type="application/json",
    )
    client.post(reverse("accounts:logout"))
    login_response = client.post(
        "/api/login",
        data=json.dumps({"email": "api@example.com", "password": "api-password"}),
        content_type="application/json",
    )
    resend = client.post(
        "/api/resend-verification",
        data=json.dumps({"email": "api@example.com"}),
        content_type="application/json",
    )
    reset_request = client.post(
        "/api/password-reset-request",
        data=json.dumps({"email": "api@example.com"}),
        content_type="application/json",
    )
    reset_token = _token_from_message(outbox[-1], "reset_url")
    reset = client.post(
        "/api/password-reset",
        data=json.dumps({"token": reset_token, "new_password": "changed-password"}),
        content_type="application/json",
    )

    assert register.status_code == 201
    assert login_response.status_code == 200
    assert resend.status_code == 200
    assert reset_request.status_code == 200
    assert reset.status_code == 200
    assert get_user_model().objects.get(email="api@example.com").check_password("changed-password")


def test_password_reset_request_does_not_send_to_alias_address(client):
    user = get_user_model().objects.create_user(email="primary@example.com", password="password")
    EmailAlias.objects.create(user=user, email="old@example.com", source="merge")

    response = client.post(reverse("accounts:password_reset_request"), {"email": "old@example.com"})

    assert response.status_code == 200
    assert outbox[0].recipient_email == "primary@example.com"


def test_social_adapter_connects_only_single_verified_alias(monkeypatch):
    user = get_user_model().objects.create_user(email="primary@example.com")
    EmailAlias.objects.create(user=user, email="old@example.com", source="merge")
    connected = []
    sociallogin = SimpleNamespace(
        is_existing=False,
        user=SimpleNamespace(pk=None),
        email_addresses=[EmailAddress(email="old@example.com", verified=True)],
        connect=lambda request, owner: connected.append(owner),
    )

    SocialAccountAdapter().pre_social_login(None, sociallogin)

    assert connected == [user]


def test_social_adapter_rejects_unmatched_slack_signup(monkeypatch):
    sociallogin = SimpleNamespace(
        is_existing=False,
        user=SimpleNamespace(pk=None),
        account=SimpleNamespace(provider="slack"),
    )

    assert SocialAccountAdapter().is_open_for_signup(None, sociallogin) is False
