from importlib import import_module

from django.core.exceptions import ImproperlyConfigured

from community_base.kernel.conf import get

BACKENDS = frozenset({"sync", "django_q", "relay"})


def get_backend():
    name = get("JOBS_BACKEND")
    if name not in BACKENDS:
        raise ImproperlyConfigured(f"Unsupported jobs backend: {name}")
    return import_module(f"community_base.jobs.backends.{name}")
