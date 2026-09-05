from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden


def staff_required(view_func):
    """Require authentication and staff status for a view."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not request.user.is_staff:
            return HttpResponseForbidden("Staff access required")
        return view_func(request, *args, **kwargs)

    return wrapper


def superuser_required(view_func):
    """Require authentication and superuser status for a view."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not request.user.is_superuser:
            return HttpResponseForbidden("Superuser access required")
        return view_func(request, *args, **kwargs)

    return wrapper
