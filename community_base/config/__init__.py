"""Typed runtime configuration."""


def get(key, default=None):
    from community_base.config.service import get as get_value

    return get_value(key, default)


def is_enabled(key):
    from community_base.config.service import is_enabled as enabled

    return enabled(key)


__all__ = ["get", "is_enabled"]
