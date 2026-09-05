from __future__ import annotations

from community_base.kernel.conf import get


def get_backend():
    name = get("MAIL_BACKEND")
    if name == "memory":
        from community_base.mail.backends import memory

        return memory
    if name == "relay":
        from community_base.mail.backends import relay

        return relay
    raise ValueError(f"unsupported mail backend: {name}")
