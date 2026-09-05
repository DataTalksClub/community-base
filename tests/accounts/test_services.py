import datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings

from community_base.accounts.models import EmailAlias, MemberProfile
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
from community_base.accounts.services.merge import MergeError, merge_accounts
from community_base.accounts.services.privacy import (
    build_user_data_export,
    delete_account_for_privacy,
    request_account_deletion,
    write_export_log,
)
from community_base.accounts.services.timezones import (
    build_timezone_options,
    format_user_datetime,
    is_valid_timezone,
)
from community_base.accounts.services.verification import unverified_user_ttl_days
from community_base.api.models import APIKey
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


def test_merge_accounts_reconciles_shared_state_and_owned_rows():
    canonical = get_user_model().objects.create_user(
        email="canonical@example.com",
        email_preferences={"events": True, "newsletter": False},
        tags=["canonical"],
    )
    secondary = get_user_model().objects.create_user(
        email="secondary@example.com",
        email_verified=True,
        unsubscribed=True,
        email_preferences={"events": False, "courses": True},
        tags=["secondary"],
        bounce_state="permanent",
        preferred_timezone="Europe/Berlin",
    )
    MemberProfile.objects.create(user=secondary, country="DE", about="Shared profile")
    EmailAlias.objects.create(user=secondary, email="older@example.com", source="merge")
    api_key, _plaintext = APIKey.create_for_user(
        user=secondary,
        name="member key",
        scopes=["profile:read"],
        kind=APIKey.Kind.MEMBER,
    )

    plan = merge_accounts(canonical, secondary)

    canonical.refresh_from_db()
    secondary.refresh_from_db()
    assert plan.secondary_deactivated is True
    assert secondary.is_active is False
    assert secondary.email == f"merged+{secondary.pk}@merged.invalid"
    assert canonical.email_verified is True
    assert canonical.unsubscribed is True
    assert canonical.bounce_state == "permanent"
    assert canonical.preferred_timezone == "Europe/Berlin"
    assert canonical.tags == ["canonical", "secondary"]
    assert canonical.email_preferences == {
        "events": False,
        "courses": True,
        "newsletter": False,
    }
    assert MemberProfile.objects.get(user=canonical).about == "Shared profile"
    assert set(canonical.email_aliases.values_list("email", flat=True)) == {
        "older@example.com",
        "secondary@example.com",
    }
    api_key.refresh_from_db()
    assert api_key.user == canonical
    assert api_key.revoked_at is not None


def test_merge_dry_run_rolls_back_every_mutation():
    canonical = get_user_model().objects.create_user(email="canonical@example.com")
    secondary = get_user_model().objects.create_user(
        email="secondary@example.com",
        email_verified=True,
    )

    plan = merge_accounts(canonical, secondary, dry_run=True)

    canonical.refresh_from_db()
    secondary.refresh_from_db()
    assert plan.dry_run is True
    assert plan.scalar_changes == ["email_verified"]
    assert canonical.email_verified is False
    assert secondary.is_active is True
    assert EmailAlias.objects.count() == 0


def test_merge_rejects_self_and_staff_without_force():
    staff = get_user_model().objects.create_user(email="staff@example.com", is_staff=True)
    member = get_user_model().objects.create_user(email="member@example.com")

    with pytest.raises(MergeError, match="itself"):
        merge_accounts(staff, staff)
    with pytest.raises(MergeError, match="force"):
        merge_accounts(member, staff)


def test_privacy_export_contains_portable_data_without_credentials():
    user = get_user_model().objects.create_user(
        email="member@example.com",
        password="secret-password",
        tags=["member"],
    )
    MemberProfile.objects.create(user=user, country="DE", about="About me")
    EmailAlias.objects.create(user=user, email="old@example.com", source="merge")

    exported = build_user_data_export(user)
    log = write_export_log(user)

    assert exported["account"]["email"] == "member@example.com"
    assert exported["account"]["tags"] == ["member"]
    assert "password" not in exported["account"]
    assert exported["member_profile"]["about"] == "About me"
    assert exported["email_aliases"][0]["email"] == "old@example.com"
    assert log.normalized_email_hash != user.email
    assert "member@example.com" not in log.normalized_email_hash


def test_deletion_request_is_idempotent():
    user = get_user_model().objects.create_user(email="member@example.com")

    first, created = request_account_deletion(user)
    second, created_again = request_account_deletion(user)

    assert created is True
    assert created_again is False
    assert first.pk == second.pk


def test_privacy_delete_anonymizes_retained_delivery_and_deletes_user():
    user = get_user_model().objects.create_user(email="member@example.com")
    with transaction.atomic():
        delivery = send(
            "accounts.private_notice",
            user.email,
            {"private": "value"},
            "accounts:test:privacy-delete",
            user=user,
        )
    request, _created = request_account_deletion(user)
    user_id = user.pk

    result = delete_account_for_privacy(user)

    delivery.refresh_from_db()
    request.refresh_from_db()
    assert result.deleted is True
    assert get_user_model().objects.filter(pk=user_id).exists() is False
    assert delivery.recipient_user is None
    assert delivery.recipient_email.endswith("@deleted.invalid")
    assert delivery.context_data == {}
    assert request.status == "completed"


def test_privacy_delete_respects_site_blocker():
    user = get_user_model().objects.create_user(email="member@example.com")
    configured = {
        "ACCOUNT_DELETION_BLOCKER": lambda **kwargs: "active_subscription",
    }

    with override_settings(COMMUNITY_BASE=configured):
        result = delete_account_for_privacy(user)

    assert result.deleted is False
    assert result.blocker_reason == "active_subscription"
    assert get_user_model().objects.filter(pk=user.pk).exists() is True
