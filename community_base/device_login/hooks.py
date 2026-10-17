"""Site extension points for the device flow.

The package never imports a site app (tests/test_boundaries.py). A site
customizes minting and the admin definition through COMMUNITY_BASE keys:

- DEVICE_LOGIN_TOKEN_MINTER: dotted path to
  `minter(*, user, label, request) -> dict`. The dict must carry `token`
  and may carry `token_id`, `expires_at` and `user`. The default mints a
  staff `community_base.api` key with DEVICE_LOGIN_SCOPES.
- DEVICE_LOGIN_ADMIN_CHECK: dotted path to `check(user) -> bool`.
  The default is `is_staff or is_superuser`.
"""

from __future__ import annotations

from django.utils.module_loading import import_string

from community_base.kernel.conf import get


def is_device_admin(user) -> bool:
    dotted = get("DEVICE_LOGIN_ADMIN_CHECK")
    if dotted:
        return bool(import_string(dotted)(user))
    if not getattr(user, "is_active", False):
        return False
    return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))


def mint_device_credential(*, user, label: str, request) -> dict:
    dotted = get("DEVICE_LOGIN_TOKEN_MINTER")
    if dotted:
        return dict(import_string(dotted)(user=user, label=label, request=request))
    from community_base.api.models import APIKey

    _, plaintext = APIKey.create_for_user(
        user=user,
        name=f"Device login {label}"[:120] or "Device login",
        scopes=list(get("DEVICE_LOGIN_SCOPES")),
        kind=APIKey.Kind.STAFF,
    )
    key = APIKey.objects.filter(lookup_prefix=plaintext[: APIKey.LOOKUP_PREFIX_LENGTH]).first()
    return {
        "token": plaintext,
        "token_id": key.masked_prefix if key else None,
        "expires_at": None,
        "user": {
            "email": getattr(user, "email", ""),
            "name": getattr(user, "get_full_name", lambda: "")() or "",
        },
    }
