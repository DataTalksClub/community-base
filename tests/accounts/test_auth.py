import json
import re
from importlib.resources import files
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialApp
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.urls import reverse

from community_base.accounts.adapters import SocialAccountAdapter
from community_base.accounts.models import EmailAlias
from community_base.accounts.settings import allauth_settings
from community_base.accounts.signals import mark_social_account_added
from community_base.accounts.tokens import (
    generate_password_reset_token,
    generate_verification_token,
)
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
    assert configured["ACCOUNT_SIGNUP_REDIRECT_URL"] == "/"
    assert configured["ACCOUNT_USER_MODEL_USERNAME_FIELD"] is None
    assert configured["SOCIALACCOUNT_ADAPTER"] == (
        "community_base.accounts.adapters.SocialAccountAdapter"
    )
    assert configured["SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT"] is True
    assert configured["SOCIALACCOUNT_PROVIDERS"]["github"]["SCOPE"] == ["user:email"]


def test_public_pages_render_from_package(client):
    for name, text in (
        ("account_login", "Sign in"),
        ("account_register", "Create an account"),
        ("account_password_reset_request", "Reset password"),
    ):
        response = client.get(reverse(name))
        assert response.status_code == 200
        assert text.encode() in response.content
        assert b'class="cb-page"' in response.content


def test_public_templates_follow_the_shared_contract():
    allowed_blocks = {
        "title",
        "meta_description",
        "page_head_metadata",
        "content",
        "extra_js",
    }
    template_dir = files("community_base.accounts").joinpath("templates/accounts")

    for template in template_dir.iterdir():
        if template.suffix != ".html":
            continue
        source = template.read_text()
        assert '{% extends "base.html" %}' in source
        assert set(re.findall(r"{% block ([a-z_]+) %}", source)) <= allowed_blocks
        for class_value in re.findall(r'class="([^"]+)"', source):
            assert all(name.startswith("cb-") for name in class_value.split())


def test_login_lists_only_configured_oauth_providers(client):
    provider = SocialApp.objects.create(
        provider="google",
        name="Google",
        client_id="google-client",
        secret="google-secret",
    )
    provider.sites.add(Site.objects.get_current())

    response = client.get(reverse("account_login"))

    assert response.status_code == 200
    assert b"Sign in with Google" in response.content
    assert b'href="/accounts/google/login/' in response.content
    assert b"Sign in with GitHub" not in response.content
    assert b"Sign in with Slack" not in response.content


def test_legacy_signup_redirect_preserves_only_safe_next(client):
    safe = client.get("/accounts/signup/?next=/events/42/")
    unsafe = client.get("/accounts/signup/?next=https://evil.example/")

    assert safe.status_code == unsafe.status_code == 302
    assert safe.url == "/accounts/register/?next=%2Fevents%2F42%2F"
    assert unsafe.url == "/accounts/register/"


def test_registration_queues_verification_logs_in_and_verifies(client):
    response = client.post(
        reverse("account_register"),
        {"email": "New@Example.com", "password": "strong-passphrase"},
    )

    assert response.status_code == 302
    assert response.url == reverse("account_verification_sent")
    user = get_user_model().objects.get(email="new@example.com")
    assert user.email_verified is False
    assert user.signup_source == "signup"
    assert user.verification_expires_at is not None
    assert str(user.pk) == client.session["_auth_user_id"]
    assert len(outbox) == 1
    assert outbox[0].purpose == "accounts.verify_email"
    assert outbox[0].context["verify_url"].startswith("http://testserver/api/verify-email?token=")

    token = _token_from_message(outbox[0], "verify_url")
    response = client.get(reverse("account_verify_email"), {"token": token})
    user.refresh_from_db()
    assert response.status_code == 200
    assert user.email_verified is True
    assert user.account_activated is True
    assert user.verification_expires_at is None
    assert response["Cache-Control"] == "private, no-store, max-age=0"


def test_registration_rejects_duplicate_email_case_insensitively(client):
    get_user_model().objects.create_user(email="member@example.com", password="password")

    response = client.post(
        reverse("account_register"),
        {"email": "MEMBER@example.com", "password": "strong-passphrase"},
    )

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert get_user_model().objects.count() == 1
    assert outbox == []


def test_verification_does_not_redirect_to_external_return(client):
    user = get_user_model().objects.create_user(email="member@example.com", password="password")
    token = generate_verification_token(user, return_path="https://example.net/stolen")

    response = client.get(reverse("account_verify_email"), {"token": token})

    assert response.status_code == 200
    assert b"Your email address is verified" in response.content


def test_verification_rejects_password_reset_token(client):
    user = get_user_model().objects.create_user(email="member@example.com", password="password")

    response = client.get(
        reverse("account_verify_email"),
        {"token": generate_password_reset_token(user)},
    )

    assert response.status_code == 400
    assert b"verification link is invalid" in response.content


def test_registration_preserves_safe_verification_return(client):
    client.post(
        reverse("account_register"),
        {
            "email": "return@example.com",
            "password": "strong-passphrase",
            "next": "/events/42/",
        },
    )
    token = _token_from_message(outbox[0], "verify_url")

    response = client.get(reverse("account_verify_email"), {"token": token})

    assert response.status_code == 302
    assert response.url == "/events/42/"


def test_login_accepts_primary_email_and_safe_next(client):
    user = get_user_model().objects.create_user(email="member@example.com", password="password")

    response = client.post(
        reverse("account_login") + "?next=/events/",
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
        reverse("account_login"),
        {"email": "old@example.com", "password": "password"},
    )
    client.post(reverse("account_logout"))
    disabled_response = client.post(
        reverse("account_login"),
        {"email": "disabled@example.com", "password": "password"},
    )

    assert alias_response.status_code == 302
    assert disabled_response.status_code == 200
    assert b"Invalid email or password" in disabled_response.content


def test_password_reset_is_non_enumerating_and_completes(client):
    user = get_user_model().objects.create_user(email="member@example.com", password="old-password")

    missing = client.post(
        reverse("account_password_reset_request"), {"email": "absent@example.com"}
    )
    existing = client.post(
        reverse("account_password_reset_request"), {"email": "member@example.com"}
    )

    assert missing.status_code == existing.status_code == 200
    assert missing.content == existing.content
    assert len(outbox) == 1
    assert outbox[0].context["reset_url"].startswith("http://testserver/api/password-reset?token=")
    token = _token_from_message(outbox[0], "reset_url")

    form = client.get(reverse("account_password_reset"), {"token": token})
    completed = client.post(
        reverse("account_password_reset"),
        {"token": token, "new_password": "new-strong-password"},
    )
    user.refresh_from_db()
    replay = client.get(reverse("account_password_reset"), {"token": token})

    assert form.status_code == 200
    assert completed.status_code == 302
    assert completed.url == reverse("account_password_reset_complete")
    assert user.check_password("new-strong-password")
    assert user.account_activated is True
    assert replay.status_code == 400


def test_api_registration_login_resend_and_reset(client):
    register = client.post(
        "/api/register",
        data=json.dumps({"email": "api@example.com", "password": "api-password"}),
        content_type="application/json",
    )
    client.post(reverse("account_logout"))
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


def test_resend_verification_creates_a_fresh_delivery(client):
    user = get_user_model().objects.create_user(email="member@example.com", password="password")

    for _attempt in range(2):
        response = client.post(
            "/api/resend-verification",
            data=json.dumps({"email": user.email}),
            content_type="application/json",
        )
        assert response.status_code == 200

    assert len(outbox) == 2
    assert outbox[0].context["verify_url"] != outbox[1].context["verify_url"]


def test_public_resend_uses_stable_route_and_non_enumerating_result(client):
    get_user_model().objects.create_user(email="member@example.com", password="password")

    response = client.post(
        "/accounts/resend-verification",
        {"email": "member@example.com"},
    )

    assert reverse("account_resend_verification") == "/accounts/resend-verification"
    assert response.status_code == 302
    assert response.url == reverse("account_verification_sent")
    assert len(outbox) == 1


def test_password_reset_request_does_not_send_to_alias_address(client):
    user = get_user_model().objects.create_user(email="primary@example.com", password="password")
    EmailAlias.objects.create(user=user, email="old@example.com", source="merge")

    response = client.post(reverse("account_password_reset_request"), {"email": "old@example.com"})

    assert response.status_code == 200
    assert outbox[0].recipient_email == "primary@example.com"


def test_social_adapter_connects_only_single_verified_alias():
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


def test_social_adapter_rejects_unmatched_slack_signup():
    sociallogin = SimpleNamespace(
        is_existing=False,
        user=SimpleNamespace(pk=None),
        account=SimpleNamespace(provider="slack"),
    )

    assert SocialAccountAdapter().is_open_for_signup(None, sociallogin) is False


def test_social_account_signal_marks_identity_and_populates_name():
    user = get_user_model().objects.create_user(email="oauth@example.com")
    sociallogin = SimpleNamespace(
        user=user,
        email_addresses=[EmailAddress(email=user.email, verified=True)],
        account=SimpleNamespace(
            provider="github",
            extra_data={"name": "Ada Lovelace"},
        ),
    )

    mark_social_account_added(None, None, sociallogin)

    user.refresh_from_db()
    assert user.email_verified is True
    assert user.account_activated is True
    assert user.signup_source == "oauth"
    assert user.first_name == "Ada"
    assert user.last_name == "Lovelace"


def test_social_login_does_not_verify_an_unverified_provider_email():
    user = get_user_model().objects.create_user(email="oauth@example.com")
    sociallogin = SimpleNamespace(
        user=user,
        email_addresses=[EmailAddress(email=user.email, verified=False)],
        account=SimpleNamespace(provider="github", extra_data={}),
    )

    mark_social_account_added(None, None, sociallogin)

    user.refresh_from_db()
    assert user.email_verified is False
    assert user.account_activated is True
