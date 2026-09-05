import datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings

from community_base.accounts.models import EmailAlias
from community_base.accounts.preferences import resolve_mail_preference
from community_base.accounts.services.email_change import (
    EmailUnavailable,
    InvalidPassword,
    confirm_email_change,
    request_email_change,
)
from community_base.accounts.services.email_resolution import (
    normalize_email,
    resolve_user_by_email,
)
from community_base.accounts.services.free_welcome import send_free_welcome
from community_base.accounts.services.timezones import (
    build_timezone_options,
    format_user_datetime,
    is_valid_timezone,
)
from community_base.accounts.services.verification import unverified_user_ttl_days
from community_base.mail import send
from community_base.mail.backends.memory import outbox
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def clear_outbox():
    outbox.clear()
    yield
    outbox.clear()


def test_email_resolution_prefers_active_primary_then_active_alias():
    primary = get_user_model().objects.create_user(email="primary@example.com")
    canonical = get_user_model().objects.create_user(email="canonical@example.com")
    EmailAlias.objects.create(user=canonical, email="old@example.com", source="merge")
    get_user_model().objects.create_user(email="disabled@example.com", is_active=False)

    assert normalize_email(" Primary@EXAMPLE.com ") == "primary@example.com"
    assert resolve_user_by_email("PRIMARY@example.com") == primary
    assert resolve_user_by_email("old@example.com") == canonical
    assert resolve_user_by_email("disabled@example.com") is None
    assert resolve_user_by_email("") is None


@pytest.mark.parametrize("configured", [None, "bad", 0, -2, True])
def test_verification_ttl_rejects_invalid_configuration(configured):
    with override_settings(COMMUNITY_BASE={"ACCOUNT_UNVERIFIED_TTL_DAYS": configured}):
        assert unverified_user_ttl_days() == 7


def test_verification_ttl_accepts_positive_integer_string():
    with override_settings(COMMUNITY_BASE={"ACCOUNT_UNVERIFIED_TTL_DAYS": "14"}):
        assert unverified_user_ttl_days() == 14


@pytest.mark.parametrize(
    ("attributes", "category", "decision"),
    [
        ({}, "events", True),
        ({"unsubscribed": True}, None, "global_unsubscribed"),
        ({"bounce_state": "permanent"}, None, "permanent_bounce"),
        ({"email_preferences": {"events": False}}, "events", "category_suppressed"),
        ({"email_preferences": {"events": False}}, "newsletter", True),
    ],
)
def test_mail_preference_resolution(attributes, category, decision):
    user = type("UserLike", (), attributes)()

    assert (
        resolve_mail_preference(purpose="notice", category=category, to="x@example.com", user=user)
        == decision
    )


def test_default_mail_resolver_records_suppressed_delivery():
    user = get_user_model().objects.create_user(
        email="member@example.com",
        unsubscribed=True,
    )

    with transaction.atomic():
        delivery = send(
            "accounts.notice",
            user.email,
            {},
            "accounts:test:suppressed",
            user=user,
        )

    delivery.refresh_from_db()
    assert delivery.state == EmailDelivery.State.SUPPRESSED
    assert delivery.reason_code == "global_unsubscribed"
    assert delivery.job is None


def test_timezone_helpers_validate_sort_and_format():
    user = type("UserLike", (), {"preferred_timezone": "Europe/Berlin"})()
    value = datetime.datetime(2026, 1, 15, 12, 0, tzinfo=datetime.UTC)

    assert is_valid_timezone("Europe/Berlin") is True
    assert is_valid_timezone("Mars/Olympus") is False
    assert format_user_datetime(value, user).endswith("Europe/Berlin")
    assert format_user_datetime(value, None).endswith("UTC")
    options = build_timezone_options()
    assert options == sorted(options, key=lambda option: (option.offset_minutes, option.value))


def test_email_change_requires_password_and_available_address():
    user = get_user_model().objects.create_user(email="member@example.com", password="password")
    get_user_model().objects.create_user(email="taken@example.com")

    with pytest.raises(InvalidPassword):
        request_email_change(user, "new@example.com", "wrong")
    with pytest.raises(EmailUnavailable):
        request_email_change(user, "taken@example.com", "password")


def test_email_change_supersedes_then_confirms_atomically():
    user = get_user_model().objects.create_user(email="member@example.com", password="password")

    first, first_token = request_email_change(user, "first@example.com", "password")
    second, second_token = request_email_change(user, "second@example.com", "password")
    first.refresh_from_db()

    assert first.invalidated_at is not None
    assert confirm_email_change(first_token).status == "superseded"
    result = confirm_email_change(second_token)
    user.refresh_from_db()
    second.refresh_from_db()
    assert result.success is True
    assert user.email == "second@example.com"
    assert user.email_verified is True
    assert second.confirmed_at is not None
    assert EmailAlias.objects.get(email="member@example.com").user == user
    assert confirm_email_change(second_token).status == "reused"
    assert [message.purpose for message in outbox] == [
        "accounts.email_change_confirm",
        "accounts.email_change_confirm",
        "accounts.email_changed_notice",
    ]


def test_email_change_rechecks_collision_at_confirmation():
    user = get_user_model().objects.create_user(email="member@example.com", password="password")
    _change, token = request_email_change(user, "later@example.com", "password")
    get_user_model().objects.create_user(email="later@example.com")

    result = confirm_email_change(token)

    user.refresh_from_db()
    assert result.status == "collision"
    assert user.email == "member@example.com"


def test_free_welcome_is_durable_and_idempotent():
    user = get_user_model().objects.create_user(email="member@example.com")

    first = send_free_welcome(user)
    second = send_free_welcome(user)

    assert first.pk == second.pk
    assert len(outbox) == 1
