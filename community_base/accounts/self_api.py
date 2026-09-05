from functools import wraps

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils.cache import patch_cache_control, patch_vary_headers

from community_base.accounts.services.account_settings import (
    AccountSettingsError,
    serialize_account,
    update_account_settings,
)
from community_base.accounts.services.privacy import (
    build_user_data_export,
    request_account_deletion,
    write_export_log,
)
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
    if request.method == "GET":
        return JsonResponse({"account": serialize_account(request.user)})
    if request.method != "PATCH":
        raise APIError(405, "method_not_allowed", "Method is not allowed.")
    try:
        account = update_account_settings(request.user, read_json_object(request))
    except AccountSettingsError as error:
        raise APIError(400, error.code, error.message, details=error.details) from error
    return JsonResponse({"account": account})


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


@session_api
def me_password(request):
    if request.method != "POST":
        raise APIError(405, "method_not_allowed", "Method is not allowed.")
    values = read_json_object(request)
    current_password = values.get("current_password", "")
    new_password = values.get("new_password", "")
    if not isinstance(current_password, str) or not isinstance(new_password, str):
        raise APIError(400, "invalid_password_fields", "Password fields must be strings.")
    user = request.user
    if user.has_usable_password() and not user.check_password(current_password):
        raise APIError(400, "invalid_current_password", "Current password is incorrect.")
    if not new_password:
        raise APIError(400, "new_password_required", "New password is required.")
    try:
        validate_password(new_password, user)
    except ValidationError as error:
        raise APIError(
            400,
            "invalid_new_password",
            "New password does not meet the password policy.",
            details={"messages": error.messages},
        ) from error
    user.set_password(new_password)
    user.account_activated = True
    user.save(update_fields=("password", "account_activated"))
    update_session_auth_hash(request, user)
    return JsonResponse({"status": "ok"})


@session_api
def me_data_export(request):
    if request.method != "GET":
        raise APIError(405, "method_not_allowed", "Method is not allowed.")
    payload = build_user_data_export(request.user)
    write_export_log(request.user)
    response = JsonResponse(payload, json_dumps_params={"indent": 2, "sort_keys": True})
    response["Content-Disposition"] = 'attachment; filename="community-account-data.json"'
    return response


@session_api
def me_deletion_request(request):
    if request.method != "POST":
        raise APIError(405, "method_not_allowed", "Method is not allowed.")
    deletion_request, created = request_account_deletion(request.user)
    return JsonResponse(
        {
            "status": deletion_request.status,
            "request_id": deletion_request.pk,
            "created": created,
        },
        status=201 if created else 200,
    )
