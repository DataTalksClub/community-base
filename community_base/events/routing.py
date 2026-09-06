from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from community_base.kernel.conf import get


def event_url_style():
    style = get("EVENT_URL_STYLE")
    if style not in {"slug", "public_id"}:
        raise ImproperlyConfigured("EVENT_URL_STYLE must be slug or public_id.")
    return style


def event_url(event, *, route="event_detail"):
    if event_url_style() == "public_id":
        if event.public_id is None:
            raise ImproperlyConfigured("Published events require public_id routes.")
        return reverse(route, kwargs={"public_id": event.public_id, "slug": event.slug})
    return reverse(route, kwargs={"slug": event.slug})
