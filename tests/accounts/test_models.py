import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from community_base.accounts.models import (
    BounceState,
    EmailAlias,
    EmailChangeRequest,
    ImportBatch,
    MemberProfile,
    PrivacyRequestLog,
)

pytestmark = pytest.mark.django_db


def test_accounts_user_is_email_first_and_uses_kept_table():
    model = get_user_model()

    assert model.__module__ == "community_base.accounts.models"
    assert model._meta.app_label == "accounts"
    assert model._meta.db_table == "accounts_user"
    assert model.USERNAME_FIELD == "email"
    assert model.REQUIRED_FIELDS == []
    assert "username" not in {field.name for field in model._meta.get_fields()}


def test_user_manager_requires_email_and_creates_unusable_password():
    model = get_user_model()

    with pytest.raises(ValueError, match="Email is required"):
        model.objects.create_user("")
    user = model.objects.create_user("member@EXAMPLE.COM")

    assert user.email == "member@example.com"
    assert not user.has_usable_password()
    assert not user.is_staff
    assert not user.is_superuser


def test_user_manager_hashes_password_and_enforces_superuser_flags():
    model = get_user_model()
    user = model.objects.create_user("member@example.com", "plain-text")

    assert user.check_password("plain-text")
    assert user.password != "plain-text"
    with pytest.raises(ValueError, match="is_staff"):
        model.objects.create_superuser("bad@example.com", is_staff=False)
    with pytest.raises(ValueError, match="is_superuser"):
        model.objects.create_superuser("bad@example.com", is_superuser=False)


def test_user_contains_only_declared_shared_domain_fields():
    fields = {field.name for field in get_user_model()._meta.get_fields()}
    required = {
        "email_verified",
        "verification_expires_at",
        "verification_reminder_sent_at",
        "verification_resend_claimed_at",
        "verification_resend_claim_token",
        "unsubscribed",
        "email_preferences",
        "soft_bounce_count",
        "bounce_state",
        "bounce_recorded_at",
        "last_bounce_diagnostic",
        "slack_user_id",
        "slack_member",
        "slack_checked_at",
        "theme_preference",
        "preferred_timezone",
        "dashboard_dismissals",
        "tags",
        "signup_source",
        "account_activated",
        "import_source",
        "imported_at",
        "import_metadata",
    }
    site_owned = {
        "tier",
        "pending_tier",
        "billing_period_end",
        "stripe_customer_id",
        "subscription_id",
        "certificate_name",
        "registration_role",
        "dark_mode",
        "identity_state",
        "normalized_email",
    }

    assert required <= fields
    assert not fields.intersection(site_owned)


@pytest.mark.parametrize("state", BounceState.values)
def test_bounce_state_round_trips_every_declared_value(state):
    user = get_user_model().objects.create_user("bounce@example.com", bounce_state=state)
    assert get_user_model().objects.get(pk=user.pk).bounce_state == state


def test_email_alias_is_unique_and_cascades_with_user():
    user = get_user_model().objects.create_user("primary@example.com")
    EmailAlias.objects.create(user=user, email="alias@example.com")

    with pytest.raises(IntegrityError), transaction.atomic():
        EmailAlias.objects.create(user=user, email="alias@example.com")
    user.delete()

    assert not EmailAlias.objects.exists()


def test_email_change_request_allows_only_one_active_request_per_user():
    user = get_user_model().objects.create_user("old@example.com")
    now = timezone.now()
    first = EmailChangeRequest.objects.create(
        user=user,
        old_email=user.email,
        new_email="new@example.com",
        token_hash="a" * 64,
        expires_at=now + timedelta(hours=1),
        last_sent_at=now,
    )

    assert first.is_pending
    with pytest.raises(IntegrityError), transaction.atomic():
        EmailChangeRequest.objects.create(
            user=user,
            old_email=user.email,
            new_email="other@example.com",
            token_hash="b" * 64,
            expires_at=now + timedelta(hours=1),
            last_sent_at=now,
        )
    first.invalidated_at = now
    first.save(update_fields=("invalidated_at",))
    replacement = EmailChangeRequest.objects.create(
        user=user,
        old_email=user.email,
        new_email="other@example.com",
        token_hash="b" * 64,
        expires_at=now + timedelta(hours=1),
        last_sent_at=now,
    )
    assert replacement.is_pending


def test_privacy_log_allows_only_one_active_deletion_request():
    values = {
        "request_type": PrivacyRequestLog.RequestType.DELETION_REQUEST,
        "status": PrivacyRequestLog.Status.REQUESTED,
        "old_user_id": 42,
        "normalized_email_hash": "a" * 64,
    }
    PrivacyRequestLog.objects.create(**values)

    with pytest.raises(IntegrityError), transaction.atomic():
        PrivacyRequestLog.objects.create(**values)


def test_import_batch_defaults_to_running_audit_state():
    batch = ImportBatch.objects.create(source="slack", dry_run=True)

    assert batch.status == ImportBatch.Status.RUNNING
    assert batch.users_created == 0
    assert batch.errors == []
    assert batch.dry_run


def test_member_profile_is_private_one_to_one_versioned_state():
    user = get_user_model().objects.create_user("profile@example.com")
    profile = MemberProfile.objects.create(user=user)

    assert profile.pk is not None
    assert user.member_profile == profile
    assert profile.completion_version == 0
    assert profile.revision == 0
    assert profile.confirmed_revision == 0
    with pytest.raises(IntegrityError), transaction.atomic():
        MemberProfile.objects.create(user=user)


def test_member_profile_normalizes_country_and_plain_text():
    user = get_user_model().objects.create_user("profile@example.com")
    profile = MemberProfile(
        user=user,
        country="de",
        organisation="  Data Org  ",
        about="  About me  ",
        ambitions="  Learn  ",
        why_joined="  Community  ",
    )

    profile.full_clean()

    assert profile.country == "DE"
    assert profile.organisation == "Data Org"
    assert profile.about == "About me"
    assert profile.ambitions == "Learn"
    assert profile.why_joined == "Community"


@pytest.mark.parametrize("country", ["ZZ", "D", "DEU", "12"])
def test_member_profile_rejects_non_iso_country_codes(country):
    profile = MemberProfile(
        user=get_user_model().objects.create_user(f"{country.lower()}@example.com"),
        country=country,
    )
    with pytest.raises(ValidationError, match="ISO 3166"):
        profile.full_clean()


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/profile",
        "javascript:alert(1)",
        "https://user@example.com/profile",
        "https://user:password@example.com/profile",
        "https://example.com/line\nbreak",
    ],
)
def test_member_profile_rejects_unsafe_links(url):
    profile = MemberProfile(
        user=get_user_model().objects.create_user(uuid_email()),
        github_url=url,
    )
    with pytest.raises(ValidationError):
        profile.full_clean()


def test_member_profile_accepts_bounded_http_links():
    profile = MemberProfile(
        user=get_user_model().objects.create_user("links@example.com"),
        github_url="https://github.com/example",
        linkedin_url="https://www.linkedin.com/in/example",
        website_url="http://example.com/about",
    )
    profile.full_clean()


def uuid_email():
    return f"{uuid.uuid4()}@example.com"
