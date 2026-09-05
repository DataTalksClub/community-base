from importlib import import_module

from django.core.exceptions import ImproperlyConfigured

from community_base.kernel.conf import get

LOCAL_BACKENDS = frozenset({"sync", "django_q"})


def get_backend():
    name = get("JOBS_BACKEND")
    if name not in LOCAL_BACKENDS:
        raise ImproperlyConfigured(f"Unsupported jobs backend in C1.1a: {name}")
    return import_module(f"community_base.jobs.backends.{name}")
