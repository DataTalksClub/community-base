from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULTS = {
    "SITE_KEY": "",
    "ACCESS_POLICY": "community_base.kernel.access.OpenPolicy",
    "JOBS_BACKEND": "sync",
    "MAIL_BACKEND": "memory",
    "MAIL_PREFERENCE_RESOLVER": "community_base.mail.preferences.allow_all",
    "MAIL_SEND_RECORDER": None,
    "MAIL_TEMPLATE_OVERRIDE_LOADER": None,
    "RELAY_API_KEY": "",
    "RELAY_BASE_URL": "",
    "RELAY_WEBHOOK_SECRET": "",
    "SITE_URL": "",
    "STUDIO_TITLE": "Community Studio",
}


def get(name):
    """Return a validated package setting with the site override applied."""

    if name not in DEFAULTS:
        raise ImproperlyConfigured(f"Unknown COMMUNITY_BASE setting: {name}")
    configured = getattr(settings, "COMMUNITY_BASE", {}) if settings.configured else {}
    return configured.get(name, DEFAULTS[name])
