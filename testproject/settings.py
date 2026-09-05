import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from community_base.accounts.settings import allauth_settings

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "community-base-test-secret-key-for-tests"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

INSTALLED_APPS = [
    "testproject",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.slack",
    "community_base.kernel",
    "community_base.accounts",
    "community_base.questionnaires",
    "community_base.onboarding",
    "community_base.community",
    "community_base.notifications",
    "community_base.comments",
    "community_base.api",
    "community_base.config",
    "community_base.jobs",
    "community_base.mail",
    "community_base.studio",
    "community_base.content_sync",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "testproject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "testproject" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "testproject.wsgi.application"


def database_name():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return BASE_DIR / "testproject" / "db.sqlite3"

    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError("The test project supports only sqlite DATABASE_URL values")
    if parsed.netloc:
        return unquote(f"//{parsed.netloc}{parsed.path}")
    return unquote(parsed.path)


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": database_name(),
    }
}

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = []
AUTH_USER_MODEL = "accounts.User"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SITE_ID = 1

globals().update(allauth_settings())
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

COMMUNITY_BASE = {
    "SITE_KEY": "test",
    "ACCESS_POLICY": "community_base.kernel.access.OpenPolicy",
    "JOBS_BACKEND": "sync",
    "MAIL_BACKEND": "memory",
    "RELAY_API_KEY": "",
    "RELAY_BASE_URL": "",
    "RELAY_WEBHOOK_SECRET": "test-relay-webhook-secret",
    "SITE_URL": "http://testserver",
    "STUDIO_TITLE": "Community Base Studio",
    "STUDIO_AUDIT_WRITER": "community_base.studio.audit.discard_audit_event",
    "USER_TAGS_ACCESSOR": "testproject.studio_tags.TestUserTagsAccessor",
}
