import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.functions import Now

from community_base.kernel.conf import get

DEFAULT_UNVERIFIED_USER_TTL_DAYS = 7


def unverified_user_ttl_days():
    raw = get("ACCOUNT_UNVERIFIED_TTL_DAYS")
    if isinstance(raw, bool):
        return DEFAULT_UNVERIFIED_USER_TTL_DAYS
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_UNVERIFIED_USER_TTL_DAYS
    return value if value > 0 else DEFAULT_UNVERIFIED_USER_TTL_DAYS


def claim_verification_resend(user_id, *, cooldown_seconds=60):
    token = uuid.uuid4()
    cutoff = Now() - timedelta(seconds=cooldown_seconds)
    claimed = (
        get_user_model()
        .objects.filter(pk=user_id, email_verified=False)
        .filter(
            Q(verification_resend_claimed_at__isnull=True)
            | Q(verification_resend_claimed_at__lte=cutoff)
        )
        .update(
            verification_resend_claimed_at=Now(),
            verification_resend_claim_token=token,
        )
    )
    return token if claimed == 1 else None


def release_verification_resend(user_id, token):
    return (
        get_user_model()
        .objects.filter(
            pk=user_id,
            verification_resend_claim_token=token,
        )
        .update(
            verification_resend_claimed_at=None,
            verification_resend_claim_token=None,
        )
    )
