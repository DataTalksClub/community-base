from community_base.events.models import EventRegistration
from community_base.events.routing import event_url
from community_base.events.tokens import generate_registration_token
from community_base.kernel.conf import require


def resolve_delivery_context(*, delivery, context):
    resolved = dict(context)
    registration_id = resolved.pop("registration_id", None)
    registration_version = resolved.pop("registration_version", None)
    if registration_id is None or registration_version is None:
        return resolved
    registration = EventRegistration.objects.filter(pk=registration_id).first()
    if registration is None or registration.version != registration_version:
        raise ValueError("Event registration mail context is stale.")
    if delivery.purpose == "events.verify_registration":
        site_url = require("SITE_URL").rstrip("/")
        token = generate_registration_token(
            registration,
            action="verify",
            issued_at=delivery.created_at,
            jti=delivery.id,
        )
        resolved["verify_url"] = f"{site_url}/events/registration/verify/?token={token}"
    elif delivery.purpose in {"events.registration_confirmed", "events.guest_invitation"}:
        site_url = require("SITE_URL").rstrip("/")
        token = generate_registration_token(
            registration,
            action="manage",
            issued_at=delivery.created_at,
            jti=delivery.id,
            expiry_hours=24 * 365,
        )
        resolved["manage_url"] = f"{site_url}/events/registration/manage/?token={token}"
    elif delivery.purpose == "events.event_cancelled":
        site_url = require("SITE_URL").rstrip("/")
        base_url = f"{site_url}{event_url(registration.event)}"
        resolved["event_url"] = base_url
        # For a cancelled event this endpoint serves the METHOD:CANCEL ICS,
        # so the guest's calendar entry is removed with one click.
        resolved["calendar_cancel_url"] = f"{base_url}calendar.ics"
    return resolved
