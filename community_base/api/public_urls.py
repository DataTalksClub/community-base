"""Build absolute URLs for package-owned public API resources."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ImproperlyConfigured
from django.urls import NoReverseMatch

from community_base.kernel.conf import get


def public_url(resource, *, is_public: bool) -> str | None:
    """Return a resource's absolute canonical public URL, or ``None``.

    Public resources provide their route through ``get_absolute_url``. The
    configured ``SITE_URL`` supplies the origin and optional path prefix; the
    request host is deliberately not involved.
    """

    if not is_public:
        return None

    try:
        route = resource.get_absolute_url()
    except (AttributeError, ImproperlyConfigured, NoReverseMatch):
        return None
    if not isinstance(route, str) or not route:
        return None

    try:
        route_parts = urlsplit(route)
    except ValueError:
        return None
    if route_parts.scheme or route_parts.netloc or not route_parts.path.startswith("/"):
        return None

    try:
        site_parts = urlsplit(str(get("SITE_URL") or "").strip())
    except ValueError:
        return None
    if site_parts.scheme not in {"http", "https"} or not site_parts.netloc:
        return None
    if site_parts.query or site_parts.fragment:
        return None

    base_path = site_parts.path.rstrip("/")
    path = f"{base_path}/{route_parts.path.lstrip('/')}"
    return urlunsplit(
        (site_parts.scheme, site_parts.netloc, path, route_parts.query, route_parts.fragment)
    )
