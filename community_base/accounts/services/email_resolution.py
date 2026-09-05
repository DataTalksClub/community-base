from django.contrib.auth import get_user_model

from community_base.accounts.models import EmailAlias


def normalize_email(email):
    if not email:
        return ""
    return get_user_model().objects.normalize_email(str(email).strip()).lower()


def resolve_user_by_email(email):
    """Resolve an active primary email first, then an active alias owner."""

    normalized = normalize_email(email)
    if not normalized:
        return None
    User = get_user_model()
    primary = User.objects.filter(email__iexact=normalized, is_active=True).first()
    if primary is not None:
        return primary
    alias = (
        EmailAlias.objects.select_related("user")
        .filter(email__iexact=normalized, user__is_active=True)
        .first()
    )
    return alias.user if alias else None
