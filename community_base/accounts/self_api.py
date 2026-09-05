from functools import wraps

from django.http import JsonResponse
from django.utils.cache import patch_cache_control, patch_vary_headers

from community_base.accounts.services.profile import (
    ProfileUpdateError,
    serialize_profile,
    update_profile,
)
from community_base.api.errors import APIError, error_response
from community_base.api.safety import read_json_object


def _private(response):
    patch_cache_control(response, private=True, no_cache=True, no_store=True, max_age=0)
    patch_vary_headers(response, ("Cookie",))
    return response


def session_api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _private(
                error_response(
                    request,
                    APIError(401, "authentication_required", "Sign in to access this resource."),
                )
            )
        try:
            response = view(request, *args, **kwargs)
        except APIError as error:
            response = error_response(request, error)
        return _private(response)

    return wrapped


def _profile_etag(revision):
    return f'"rev-{revision}"'


def _required_revision(request):
    raw = request.headers.get("If-Match")
    if raw is None:
        raise APIError(428, "precondition_required", "A strong If-Match revision is required.")
    if not raw.startswith('"rev-') or not raw.endswith('"'):
        raise APIError(400, "invalid_if_match", "If-Match must contain one strong revision ETag.")
    value = raw[5:-1]
    if not value.isdigit() or value != str(int(value)):
        raise APIError(400, "invalid_if_match", "If-Match must contain one strong revision ETag.")
    return int(value)


def _profile_response(user, data=None):
    payload = data if data is not None else serialize_profile(user)
    response = JsonResponse({"profile": payload})
    response["ETag"] = _profile_etag(payload["revision"])
    return response


@session_api
def me(request):
    if request.method != "GET":
        raise APIError(405, "method_not_allowed", "Method is not allowed.")
    user = request.user
    return JsonResponse(
        {
            "account": {
                "id": user.pk,
                "email": user.email,
                "email_verified": user.email_verified,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email_preferences": user.email_preferences,
                "unsubscribed": user.unsubscribed,
                "preferred_timezone": user.preferred_timezone,
                "theme_preference": user.theme_preference,
                "dashboard_dismissals": user.dashboard_dismissals,
            }
        }
    )


@session_api
def me_profile(request):
    if request.method == "GET":
        return _profile_response(request.user)
    if request.method != "PATCH":
        raise APIError(405, "method_not_allowed", "Method is not allowed.")
    values = read_json_object(request)
    try:
        state = update_profile(
            request.user,
            values,
            expected_revision=_required_revision(request),
        )
    except ProfileUpdateError as error:
        status = 409 if error.code == "revision_conflict" else 400
        raise APIError(status, error.code, error.message, details=error.details) from error
    return _profile_response(request.user, state.data)
