import datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings

from community_base.accounts.models import EmailAlias
from community_base.accounts.preferences import resolve_mail_preference
from community_base.accounts.services.email_resolution import (
    normalize_email,
    resolve_user_by_email,
)
from community_base.accounts.services.timezones import (
    build_timezone_options,
    format_user_datetime,
    is_valid_timezone,
)
from community_base.accounts.services.verification import unverified_user_ttl_days
from community_base.mail import send
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db


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
