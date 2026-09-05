from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULTS = {
    "ACCOUNT_BEFORE_DELETE_HOOK": None,
    "ACCOUNT_DELETION_BLOCKER": None,
    "ACCOUNT_MERGE_HOOK": None,
    "ACCOUNT_PRIVACY_EXPORT_HOOK": None,
    "ACCOUNT_UNVERIFIED_TTL_DAYS": 7,
    "AI_ONBOARDING": False,
    "AI_API_KEY": "",
    "AI_BASE_URL": "https://api.anthropic.com",
    "AI_MODEL": "claude-sonnet-4-5",
    "AI_MAX_RETRIES": 2,
    "CONTENT_SOURCES": [],
    "CONTENT_SYNC_GITHUB_API_URL": "https://api.github.com",
    "CONTENT_SYNC_GITHUB_APP_ID": "",
    "CONTENT_SYNC_GITHUB_INSTALLATION_ID": "",
    "CONTENT_SYNC_GITHUB_PRIVATE_KEY": "",
    "CONTENT_SYNC_HTTP_TIMEOUT": 30,
    "CONTENT_SYNC_MAX_ARCHIVE_BYTES": 100_000_000,
    "CONTENT_SYNC_MEDIA_BACKEND": "null",
    "CONTENT_SYNC_S3_BUCKET": "",
    "CONTENT_SYNC_S3_PREFIX": "content-sync",
    "CONTENT_SYNC_S3_PUBLIC_URL": "",
    "CONTENT_SYNC_S3_REGION": "",
    "SITE_KEY": "",
    "ACCESS_POLICY": "community_base.kernel.access.OpenPolicy",
    "JOBS_BACKEND": "sync",
    "MAIL_BACKEND": "memory",
    "MAIL_CONTEXT_RESOLVER": "community_base.accounts.mail_context.resolve_delivery_context",
    "MAIL_PREFERENCE_RESOLVER": "community_base.accounts.preferences.resolve_mail_preference",
    "MAIL_SEND_RECORDER": None,
    "MAIL_TEMPLATE_DIR": None,
    "MAIL_TEMPLATE_OVERRIDE_LOADER": None,
    "MAIL_UNSUBSCRIBE_URL_BUILDER": None,
    "MAIL_VERIFY_EMAIL_URL_BUILDER": None,
    "RELAY_API_KEY": "",
    "RELAY_BASE_URL": "",
    "RELAY_WEBHOOK_SECRET": "",
    "SITE_URL": "",
    "STUDIO_TITLE": "Community Studio",
    "STUDIO_AUDIT_WRITER": "community_base.studio.audit.discard_audit_event",
    "USER_TAGS_ACCESSOR": "community_base.studio.user_tags.AttributeTagsAccessor",
}


def get(name):
    """Return a validated package setting with the site override applied."""

    if name not in DEFAULTS:
        raise ImproperlyConfigured(f"Unknown COMMUNITY_BASE setting: {name}")
    configured = getattr(settings, "COMMUNITY_BASE", {}) if settings.configured else {}
    return configured.get(name, DEFAULTS[name])
