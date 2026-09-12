from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden

from community_base.kernel.hooks import Hook


class StudioAccessHooks:
    authorizer = Hook("STUDIO_AUTHORIZER", None)


_hooks = StudioAccessHooks()


def staff_required(view_func):
    """Require authentication and staff access for a view.

    With ``COMMUNITY_BASE["STUDIO_AUTHORIZER"]`` configured, that callable
    decides access: it receives the request and returns a truthy value to
    allow it. The default check is ``request.user.is_staff``.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        authorizer = _hooks.authorizer
        if authorizer is None:
            allowed = request.user.is_staff
        else:
            allowed = bool(authorizer(request))
        if not allowed:
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
