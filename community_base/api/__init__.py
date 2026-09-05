"""Shared JSON API foundation."""


def route(*args, **kwargs):
    """Register a route without importing Django models during app discovery."""
    from community_base.api.registry import route as register_route

    return register_route(*args, **kwargs)


__all__ = ["route"]
