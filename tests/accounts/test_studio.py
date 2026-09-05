from io import StringIO

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse

from community_base.accounts.models import EmailAlias, ImportBatch, PrivacyRequestLog
from community_base.accounts.services.email_change import request_email_change
from community_base.accounts.services.privacy import request_account_deletion
from community_base.mail.backends.memory import outbox

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def clear_outbox():
    outbox.clear()
    yield
    outbox.clear()


@pytest.fixture
def operator():
    return get_user_model().objects.create_user(email="operator@example.com", is_staff=True)


def _csv_upload(content="email,first_name\nnew@example.com,Ada\n"):
    return SimpleUploadedFile("members.csv", content.encode(), content_type="text/csv")


def test_account_operations_are_registered_under_people(client, operator):
    client.force_login(operator)

    response = client.get(reverse("accounts_studio_operations"))

    assert response.status_code == 200
    assert b"Account operations" in response.content
    assert b"Create user" in response.content
    assert b"Import users" in response.content
    assert b"Merge accounts" in response.content


def test_staff_create_builds_activated_passwordless_account_and_welcome(client, operator):
    client.force_login(operator)

    response = client.post(
        reverse("accounts_studio_user_create"),
        {
            "email": " New@Example.com ",
            "first_name": " Ada ",
            "email_verified": "on",
            "send_welcome": "on",
        },
    )

    user = get_user_model().objects.get(email="new@example.com")
    assert response.status_code == 302
    assert response.url == reverse("studio_user_detail", args=(user.pk,))
    assert user.first_name == "Ada"
    assert user.email_verified is True
    assert user.account_activated is True
    assert user.signup_source == "staff_create"
    assert user.has_usable_password() is False
    assert EmailAddress.objects.get(user=user, primary=True).verified is True
    assert [message.purpose for message in outbox] == ["accounts.free_welcome"]


def test_staff_create_rejects_primary_and_alias_collisions(client, operator):
    owner = get_user_model().objects.create_user(email="primary@example.com")
    EmailAlias.objects.create(user=owner, email="alias@example.com")
    client.force_login(operator)

    primary = client.post(
        reverse("accounts_studio_user_create"),
        {"email": "PRIMARY@example.com"},
    )
    alias = client.post(
        reverse("accounts_studio_user_create"),
        {"email": "ALIAS@example.com"},
    )

    assert primary.status_code == alias.status_code == 400
    assert get_user_model().objects.count() == 2


def test_staff_import_dry_run_writes_no_account_or_batch(client, operator):
    client.force_login(operator)

    response = client.post(
        reverse("accounts_studio_user_import"),
        {
            "source": "course_db",
            "csv_file": _csv_upload(),
            "dry_run": "on",
            "send_welcome": "on",
            "default_tags": "Imported, Cohort 2026",
        },
    )

    assert response.status_code == 200
    assert response.context["result"].dry_run is True
    assert response.context["result"].users_created == 1
    assert not get_user_model().objects.filter(email="new@example.com").exists()
    assert ImportBatch.objects.count() == 0
    assert outbox == []


def test_staff_live_import_redirects_to_reviewable_batch(client, operator):
    client.force_login(operator)

    response = client.post(
        reverse("accounts_studio_user_import"),
        {
            "source": "course_db",
            "csv_file": _csv_upload(),
            "default_tags": "Imported",
        },
    )

    batch = ImportBatch.objects.get()
    user = get_user_model().objects.get(email="new@example.com")
    assert response.status_code == 302
    assert response.url == reverse("accounts_studio_import_detail", args=(batch.pk,))
    assert batch.actor == operator
    assert user.tags == ["imported"]


def test_staff_merge_requires_confirmation_and_supports_dry_run(client, operator):
    canonical = get_user_model().objects.create_user(email="canonical@example.com")
    secondary = get_user_model().objects.create_user(email="secondary@example.com")
    client.force_login(operator)
    payload = {
        "canonical_user_id": canonical.pk,
        "secondary_user_id": secondary.pk,
        "confirm": "on",
    }

    dry_run = client.post(
        reverse("accounts_studio_user_merge"),
        {**payload, "dry_run": "on"},
    )
    secondary.refresh_from_db()
    assert dry_run.status_code == 200
    assert dry_run.context["result"].dry_run is True
    assert secondary.is_active is True

    merged = client.post(reverse("accounts_studio_user_merge"), payload)
    secondary.refresh_from_db()
    assert merged.status_code == 302
    assert merged.url == reverse("studio_user_detail", args=(canonical.pk,))
    assert secondary.is_active is False
    assert EmailAlias.objects.get(email="secondary@example.com").user == canonical


def test_account_operations_review_privacy_and_email_change_without_token(client, operator):
    member = get_user_model().objects.create_user(email="member@example.com", password="password")
    privacy_request, _created = request_account_deletion(member)
    change, token = request_email_change(member, "new@example.com", "password")
    client.force_login(operator)

    index = client.get(reverse("accounts_studio_operations"))
    privacy = client.get(reverse("accounts_studio_privacy_detail", args=(privacy_request.pk,)))
    email_change = client.get(reverse("accounts_studio_email_change_detail", args=(change.pk,)))

    assert index.status_code == privacy.status_code == email_change.status_code == 200
    assert b"Deletion request" in index.content
    assert b"member@example.com" in email_change.content
    assert b"new@example.com" in email_change.content
    assert token.encode() not in email_change.content
    assert change.token_hash.encode() not in email_change.content
    assert PrivacyRequestLog.objects.filter(pk=privacy_request.pk).exists()


@pytest.mark.parametrize(
    "route_name",
    [
        "accounts_studio_operations",
        "accounts_studio_user_create",
        "accounts_studio_user_import",
        "accounts_studio_user_merge",
    ],
)
def test_account_operations_deny_non_staff(client, route_name):
    member = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(member)

    assert client.get(reverse(route_name)).status_code == 403


def test_account_studio_routes_pass_partition_check():
    output = StringIO()
    call_command("studio_routes", check=True, stdout=output)

    assert output.getvalue().strip() == "OK"
