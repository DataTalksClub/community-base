"""Route names the site URLconf actually mounts, read when they are needed."""

from functools import lru_cache

from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

PACKAGE_STUDIO_URLCONF = "community_base.studio.urls"


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


def _module_name(urlconf_name) -> str:
    """The dotted module a resolver was built from, or an empty string."""

    if isinstance(urlconf_name, str):
        return urlconf_name
    return getattr(urlconf_name, "__name__", "")


@lru_cache(maxsize=32)
def _studio_mount(resolver) -> tuple[str, str]:
    """Find where the package's own Studio URL module is mounted.

    Cached on the resolver object rather than on the URLconf name: Django builds
    a new resolver whenever the URL caches are cleared, which is what happens
    when a test changes ``ROOT_URLCONF``, so a stale entry cannot be read back.
    """

    def walk(patterns, path_prefix="", namespaces=()):
        for entry in patterns:
            if not isinstance(entry, URLResolver):
                continue
            path = path_prefix + str(entry.pattern)
            nested = namespaces + (entry.namespace,) if entry.namespace else namespaces
            if _module_name(entry.urlconf_name) == PACKAGE_STUDIO_URLCONF:
                return path, ":".join(nested)
            found = walk(entry.url_patterns, path, nested)
            if found is not None:
                return found
        return None

    return walk(resolver.url_patterns) or ("studio/", "")


def studio_mount_prefix(*, resolver=None) -> str:
    """The path the site mounts the package's Studio URLs at, such as ``manage/``.

    Falls back to ``studio/`` when the module is not mounted, or is mounted as a
    copied pattern list rather than by module, so a site that mounts the Studio
    the documented way needs no setting and one that does not keeps the old
    default.
    """

    return _studio_mount(resolver or get_resolver())[0]


def studio_namespace(*, resolver=None) -> str:
    """The namespace the site mounts the package's Studio URLs under, or empty.

    This is the namespace a bare package route name is read in: the package
    registers and reverses names such as ``studio_dashboard``, and a site is
    free to mount that module under an ``app_name`` or an ``include`` namespace.
    """

    return _studio_mount(resolver or get_resolver())[1]


def qualify(name: str, namespace: str) -> str:
    """Read a route name in ``namespace`` unless it already names one."""

    if not name or not namespace or ":" in name:
        return name
    return f"{namespace}:{name}"


def unqualify(name: str, namespace: str) -> str:
    """Drop ``namespace`` from a route name that resolved under it."""

    prefix = f"{namespace}:"
    if namespace and name.startswith(prefix):
        return name[len(prefix) :]
    return name


def studio_reverse(view_name: str, args=None, kwargs=None) -> str:
    """Reverse a package Studio route wherever the site mounted it.

    The package writes its own route names bare. Mounted under a namespace they
    reverse only as ``namespace:name``, so every hard-coded ``{% url %}`` and
    ``redirect()`` in the package would raise ``NoReverseMatch`` on such a site.
    The exact name is tried first, so nothing changes for a site that mounts the
    Studio without a namespace.
    """

    try:
        return reverse(view_name, args=args, kwargs=kwargs)
    except NoReverseMatch:
        qualified = qualify(view_name, studio_namespace())
        if qualified == view_name:
            raise
        return reverse(qualified, args=args, kwargs=kwargs)
