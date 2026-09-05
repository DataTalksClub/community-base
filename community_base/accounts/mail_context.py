from community_base.accounts.tokens import (
    generate_password_reset_token,
    generate_verification_token,
)
from community_base.kernel.conf import get


def resolve_delivery_context(*, delivery, context):
    resolved = dict(context)
    user = delivery.recipient_user
    site_url = get("SITE_URL").rstrip("/")
    if delivery.purpose == "accounts.verify_email" and user is not None:
        token = generate_verification_token(
            user,
            return_path=resolved.get("return_path", ""),
            issued_at=delivery.created_at,
            jti=delivery.id,
        )
        resolved.pop("return_path", None)
        resolved["verify_url"] = f"{site_url}/api/verify-email?token={token}"
    elif delivery.purpose == "accounts.password_reset" and user is not None:
        token = generate_password_reset_token(
            user,
            issued_at=delivery.created_at,
            jti=delivery.id,
        )
        resolved["reset_url"] = f"{site_url}/api/password-reset?token={token}"
    elif delivery.purpose == "accounts.email_change_confirm":
        change_id = resolved.pop("change_request_id", None)
        if change_id is not None:
            from community_base.accounts.models import EmailChangeRequest
            from community_base.accounts.services.email_change import email_change_token

            change = EmailChangeRequest.objects.filter(pk=change_id).first()
            if change is not None:
                token = email_change_token(change)
                resolved["confirm_url"] = f"{site_url}/account/change-email/confirm?token={token}"
    return resolved
