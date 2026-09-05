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
