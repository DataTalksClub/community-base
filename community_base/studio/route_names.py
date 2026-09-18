"""Route names the site URLconf actually mounts, read when they are needed."""

from django.urls import URLPattern, URLResolver, get_resolver


def urlconf_route_names(*, prefix: str = "", resolver=None) -> set[str]:
    """Collect every mounted route name, optionally limited to one path prefix.

    A name is recorded the way ``reverse()`` takes it: a route mounted under an
    instance namespace is recorded as ``namespace:name``, and nested namespaces
    are joined in mount order, ``outer:inner:name``. A site that mounts Studio
    without a namespace is unaffected, since there is then nothing to prefix.

    The URLconf is walked on call, never at import or ``AppConfig.ready()`` time,
    so reading it cannot force URL resolution during application startup.
    """

    names: set[str] = set()

    def walk(patterns, path_prefix="", namespaces=()):
        for entry in patterns:
            path = path_prefix + str(entry.pattern)
            if isinstance(entry, URLResolver):
                nested = namespaces + (entry.namespace,) if entry.namespace else namespaces
                walk(entry.url_patterns, path, nested)
            elif isinstance(entry, URLPattern) and path.startswith(prefix) and entry.name:
                names.add(":".join(namespaces + (entry.name,)))

    walk((resolver or get_resolver()).url_patterns)
    return names
