from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from django.utils.cache import patch_cache_control, patch_vary_headers
from django.views.decorators.csrf import csrf_exempt

from community_base.api.errors import (
    authentication_required,
    error_response,
    permission_denied,
    session_authentication_required,
)
from community_base.api.models import APIKey


def _bearer_token(request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, separator, token = header.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        return None
    return token.strip()


def bearer_required(*, scopes: tuple[str, ...] = ()) -> Callable:
    required_scopes = tuple(scopes)

    def decorator(view_func: Callable) -> Callable:
        @csrf_exempt
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            api_key = APIKey.authenticate(_bearer_token(request))
            if api_key is None:
                return error_response(request, authentication_required())
            if not api_key.allows(required_scopes):
                return error_response(request, permission_denied())
            request.api_key = api_key
            request.user = api_key.user
            api_key.mark_used(request)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def session_required(view_func: Callable) -> Callable:
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            response = error_response(request, session_authentication_required())
        else:
            response = view_func(request, *args, **kwargs)
        patch_cache_control(response, private=True, no_cache=True, no_store=True, max_age=0)
        patch_vary_headers(response, ("Cookie",))
        return response

    return wrapper
