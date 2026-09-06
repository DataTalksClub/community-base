from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from community_base.events.guest_invitations import invite_guest
from community_base.events.models import Event, EventHost, EventRegistration, Host
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db(transaction=True)


def event():
    return Event.objects.create(
        title="Guest session",
        slug="guest-session",
        status="upcoming",
        start_datetime=timezone.now() + timedelta(days=2),
    )


def test_guest_invitation_is_idempotent_and_uses_durable_mail():
    item = event()

    first = invite_guest(item, "Guest@Example.com")
    second = invite_guest(item, "guest@example.com")

    assert first.created is True
    assert second.created is False
    assert first.registration == second.registration
    assert first.delivery == second.delivery
    assert first.registration.status == EventRegistration.Status.CONFIRMED
    assert EmailDelivery.objects.get().purpose == "events.guest_invitation"


def test_host_cannot_be_invited_as_guest():
    item = event()
    host = Host.objects.create(name="Host", slug="host", email="host@example.com")
    EventHost.objects.create(event=item, host=host)

    with pytest.raises(ValidationError, match="host cannot"):
        invite_guest(item, "HOST@example.com")

    assert not EventRegistration.objects.exists()


def test_guest_invitation_requires_upcoming_event():
    item = event()
    item.status = "completed"
    item.save(update_fields=("status",))

    with pytest.raises(ValidationError, match="upcoming"):
        invite_guest(item, "guest@example.com")
