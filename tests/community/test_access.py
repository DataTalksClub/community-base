import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.community.access import ensure_access_grant, reactivate_access, revoke_access
from community_base.community.models import SlackAccessGrant
from community_base.mail.backends.memory import outbox
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def clear_outbox():
    outbox.clear()


def eligible_user(email="member@example.com"):
    return get_user_model().objects.create_user(email=email, email_verified=True)


def config(settings, **overrides):
    settings.COMMUNITY_BASE = {
        "JOBS_BACKEND": "sync",
        "MAIL_BACKEND": "memory",
        "SLACK_INVITE_URL": "https://join.slack.com/example-secret",
        "SLACK_INVITE_VERSION": "v1",
        **overrides,
    }


def test_grant_and_delivery_are_idempotent_and_never_store_invite_url(settings):
    config(settings)
    user = eligible_user()

    first = ensure_access_grant(user, source=SlackAccessGrant.Source.ELIGIBILITY)
    second = ensure_access_grant(user, source=SlackAccessGrant.Source.ELIGIBILITY)

    assert first[0] == second[0]
    assert SlackAccessGrant.objects.count() == 1
    assert EmailDelivery.objects.count() == 1
    delivery = EmailDelivery.objects.get()
    assert delivery.context_data == {"invite_version": "v1"}
    assert "join.slack.com" not in str(delivery.context_data)


def test_invite_rotation_updates_grant_and_creates_one_new_delivery(settings):
    config(settings)
    user = eligible_user()
    grant, _changed, _delivery = ensure_access_grant(
        user, source=SlackAccessGrant.Source.ELIGIBILITY
    )
    config(settings, SLACK_INVITE_VERSION="v2")

    rotated, changed, _delivery = ensure_access_grant(
        user, source=SlackAccessGrant.Source.ELIGIBILITY
    )

    assert rotated.pk == grant.pk
    assert changed is True
    assert rotated.invite_version == "v2"
    assert EmailDelivery.objects.count() == 2


def test_private_reveal_requires_eligibility_and_never_caches(client, settings):
    config(settings)
    user = eligible_user()
    client.force_login(user)

    response = client.get(reverse("community_base_slack_access"))

    assert response.status_code == 200
    assert b"https://join.slack.com/example-secret" in response.content
    assert {"private", "no-store", "max-age=0"}.issubset(
        {part.strip() for part in response["Cache-Control"].split(",")}
    )
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"


def test_ineligible_member_cannot_reveal_or_create_grant(client, settings):
    config(settings)
    user = get_user_model().objects.create_user(email="unverified@example.com")
    client.force_login(user)

    response = client.get(reverse("community_base_slack_access"))

    assert response.status_code == 403
    assert b"join.slack.com" not in response.content
    assert not SlackAccessGrant.objects.exists()


def test_revoked_grant_stays_denied_until_explicit_reactivation(client, settings):
    config(settings)
    user = eligible_user()
    ensure_access_grant(user, source=SlackAccessGrant.Source.ELIGIBILITY)
    revoke_access(user)
    client.force_login(user)

    denied = client.get(reverse("community_base_slack_access"))
    reactivated, changed, _delivery = reactivate_access(user)

    assert denied.status_code == 403
    assert b"join.slack.com" not in denied.content
    assert changed is True
    assert reactivated.active is True
