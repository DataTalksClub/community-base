from community_base.events.models import EventRegistration
from community_base.events.tokens import generate_registration_token
from community_base.kernel.conf import get


def resolve_delivery_context(*, delivery, context):
    resolved = dict(context)
    registration_id = resolved.pop("registration_id", None)
    registration_version = resolved.pop("registration_version", None)
    if registration_id is None or registration_version is None:
        return resolved
    registration = EventRegistration.objects.filter(pk=registration_id).first()
    if registration is None or registration.version != registration_version:
        raise ValueError("Event registration mail context is stale.")
    site_url = get("SITE_URL").rstrip("/")
    if delivery.purpose == "events.verify_registration":
        token = generate_registration_token(
            registration,
            action="verify",
            issued_at=delivery.created_at,
            jti=delivery.id,
        )
        resolved["verify_url"] = f"{site_url}/events/registrations/verify?token={token}"
    elif delivery.purpose == "events.registration_confirmed":
        token = generate_registration_token(
            registration,
            action="manage",
            issued_at=delivery.created_at,
            jti=delivery.id,
            expiry_hours=24 * 365,
        )
        resolved["manage_url"] = f"{site_url}/events/registrations/manage?token={token}"
    return resolved
