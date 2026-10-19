"""Shared admin device login (RFC 8628-shaped)."""
 
from community_base.device_login.client import (
    DeviceLoginError,
    default_label,
    device_login,
)
from community_base.device_login.storage import (
    read_private_json,
    save_private_json,
)

__all__ = [
    "DeviceLoginError",
    "default_label",
    "device_login",
    "read_private_json",
    "save_private_json",
]
