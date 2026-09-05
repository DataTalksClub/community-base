from dataclasses import dataclass
from functools import cache
from typing import Any

from django.utils.module_loading import import_string

from community_base.kernel.conf import get


@cache
def resolve(dotted_path: str):
    """Resolve and cache a dotted Python path."""

    return import_string(dotted_path)


@dataclass(frozen=True)
class Hook:
    """Descriptor resolving a callable configured through ``COMMUNITY_BASE``."""

    name: str
    default: Any

    def __get__(self, instance, owner):
        target = get(self.name)
        if target is None:
            target = self.default
        return resolve(target) if isinstance(target, str) else target
