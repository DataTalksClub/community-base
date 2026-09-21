"""Synthetic installation proving homework steps do not need coursework."""

from testproject.settings import *  # noqa: F403

ESSENTIAL_APPS = {
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "community_base.kernel",
    "community_base.accounts",
    "community_base.api",
    "community_base.config",
    "community_base.curriculum",
    "community_base.events",
    "community_base.jobs",
    "community_base.mail",
    "community_base.homework_steps",
}
INSTALLED_APPS = [app for app in INSTALLED_APPS if app in ESSENTIAL_APPS]  # noqa: F405
ROOT_URLCONF = "tests.homework_steps.urls_curriculum_only"
