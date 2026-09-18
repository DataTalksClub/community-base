"""SITE_URL must not silently degrade into a relative link (C7.27, finding 5).

Companion to `tests/accounts/test_mail_context.py`: the same rule applied to the
events half of `mail_context.resolve_delivery_context`. `events.verify_registration`,
`events.registration_confirmed` and `events.guest_invitation` all compose an absolute
link and must raise loudly when `SITE_URL` is unset; `events.reminder` does not
compose a link and must be unaffected.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import timezone

from community_base.events.anonymous_registration import request_anonymous_registration
from community_base.events.mail_context import resolve_delivery_context
from community_base.events.models import Event

pytestmark = pytest.mark.django_db


def event(**values):
    values.setdefault("title", "Open community event")
    values.setdefault("start_datetime", timezone.now() + timedelta(days=3))
    values.setdefault("status", "upcoming")
    values.setdefault("required_level", 0)
    return Event.objects.create(**values)


def test_verify_registration_link_raises_when_site_url_is_unset():
    requested = request_anonymous_registration(event(), "person@example.com")
    delivery = requested.delivery
    assert delivery.purpose == "events.verify_registration"

    with override_settings(COMMUNITY_BASE={"SITE_URL": ""}):
        with pytest.raises(ImproperlyConfigured):
            resolve_delivery_context(delivery=delivery, context=delivery.context_data)


def test_a_purpose_that_builds_no_link_is_unaffected_by_an_unset_site_url():
    """A site legitimately missing SITE_URL is only affected the moment a delivery
    actually needs an absolute link; a reminder mail does not, so it must not raise.
    """

    requested = request_anonymous_registration(event(), "person@example.com")
    registration = requested.registration
    delivery = SimpleNamespace(purpose="events.reminder")
    context = {
        "registration_id": str(registration.pk),
        "registration_version": registration.version,
    }

    with override_settings(COMMUNITY_BASE={"SITE_URL": ""}):
        resolved = resolve_delivery_context(delivery=delivery, context=context)

    assert resolved == {}
