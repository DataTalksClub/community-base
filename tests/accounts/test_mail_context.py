"""SITE_URL must not silently degrade into a relative link (C7.27, finding 5).

`calendar.py` and `jobs/relay.py` already raise `ImproperlyConfigured` on an empty
`SITE_URL`; before this fix, `accounts/mail_context.py` was the odd one out and
composed a relative `verify_url`/`reset_url`/`confirm_url` instead. These tests pin
the two halves of the rule: a purpose that builds a link raises when `SITE_URL` is
unset, and a purpose that does not need a link is unaffected by it being unset.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from community_base.accounts.mail_context import resolve_delivery_context
from community_base.mail.backends.memory import outbox
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def clear_outbox():
    outbox.clear()
    yield
    outbox.clear()


def test_verify_email_link_raises_when_site_url_is_unset(client):
    client.post(
        reverse("account_register"),
        {"email": "member@example.com", "password": "strong-passphrase"},
    )
    delivery = EmailDelivery.objects.get(pk=outbox[0].delivery_id)
    assert delivery.purpose == "accounts.verify_email"

    with override_settings(COMMUNITY_BASE={"SITE_URL": ""}):
        with pytest.raises(ImproperlyConfigured):
            resolve_delivery_context(delivery=delivery, context=delivery.context_data)


def test_password_reset_link_raises_when_site_url_is_unset(client):
    get_user_model().objects.create_user(email="member@example.com", password="old-password")
    client.post(reverse("account_password_reset_request"), {"email": "member@example.com"})
    delivery = EmailDelivery.objects.get(pk=outbox[0].delivery_id)
    assert delivery.purpose == "accounts.password_reset"

    with override_settings(COMMUNITY_BASE={"SITE_URL": ""}):
        with pytest.raises(ImproperlyConfigured):
            resolve_delivery_context(delivery=delivery, context=delivery.context_data)


@override_settings(COMMUNITY_BASE={"SITE_URL": ""})
def test_a_purpose_that_builds_no_link_is_unaffected_by_an_unset_site_url():
    """A site legitimately missing SITE_URL is only affected the moment a delivery
    actually needs an absolute link; this purpose does not, so it must not raise.
    """

    delivery = SimpleNamespace(
        purpose="accounts.email_changed_notice",
        recipient_user=None,
        created_at=timezone.now(),
        id=uuid4(),
    )

    resolved = resolve_delivery_context(delivery=delivery, context={"old_email": "a@example.com"})

    assert resolved == {"old_email": "a@example.com"}
