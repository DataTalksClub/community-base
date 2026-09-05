from typing import Protocol

from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve

LEVEL_OPEN = 0
LEVEL_REGISTERED = 5
LEVEL_BASIC = 10
LEVEL_MAIN = 20
LEVEL_PREMIUM = 30

LEVEL_LABELS = {
    LEVEL_OPEN: "Open",
    LEVEL_REGISTERED: "Registered",
    LEVEL_BASIC: "Basic",
    LEVEL_MAIN: "Main",
    LEVEL_PREMIUM: "Premium",
}


class AccessPolicy(Protocol):
    def user_level(self, user) -> int: ...

    def can_access(self, user, required_level: int) -> bool: ...

    def level_label(self, level: int) -> str: ...


class OpenPolicy:
    """Default policy supporting open and authenticated-only content."""

    def user_level(self, user) -> int:
        return LEVEL_OPEN

    def can_access(self, user, required_level: int) -> bool:
        if required_level == LEVEL_OPEN:
            return True
        return required_level == LEVEL_REGISTERED and bool(
            user is not None and getattr(user, "is_authenticated", False)
        )

    def level_label(self, level: int) -> str:
        return LEVEL_LABELS.get(level, str(level))


class RegisteredOnlyPolicy(OpenPolicy):
    """Policy for sites whose only gates are open and registered."""


def _configured_policy() -> AccessPolicy:
    configured = get("ACCESS_POLICY")
    policy = resolve(configured) if isinstance(configured, str) else configured
    return policy() if isinstance(policy, type) else policy


def can_access(user, obj_or_level) -> bool:
    required_level = getattr(obj_or_level, "required_level", obj_or_level)
    return _configured_policy().can_access(user, required_level)


def level_label(level: int) -> str:
    return _configured_policy().level_label(level)
