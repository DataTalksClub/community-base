import re

from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from community_base.kernel.conf import get

_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")


def normalize_tag(value) -> str:
    return _SEPARATOR_RE.sub("-", str(value or "").strip().casefold()).strip("-")


def normalize_tags(values) -> list[str]:
    return sorted({tag for value in values if (tag := normalize_tag(value))})


class AttributeTagsAccessor:
    """Read and write a JSON-like ``tags`` attribute when a user model has one."""

    def get(self, user) -> list[str]:
        return normalize_tags(getattr(user, "tags", None) or [])

    def set(self, user, tags) -> None:
        if not hasattr(user, "tags"):
            raise ImproperlyConfigured(
                "The user model has no tags attribute; configure "
                "COMMUNITY_BASE['USER_TAGS_ACCESSOR']"
            )
        user.tags = normalize_tags(tags)
        user.save(update_fields=("tags",))


def accessor():
    configured = get("USER_TAGS_ACCESSOR")
    resolved = import_string(configured) if isinstance(configured, str) else configured
    return resolved() if isinstance(resolved, type) else resolved


def get_tags(user) -> list[str]:
    return normalize_tags(accessor().get(user))


def set_tags(user, tags) -> None:
    accessor().set(user, normalize_tags(tags))


def users_with_tag(users, tag):
    normalized = normalize_tag(tag)
    return [user for user in users if normalized in get_tags(user)]
