from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse

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
from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.safety import read_json_object

OBJECT_SCHEMA = {"type": "object"}
ACCOUNT_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["account"],
    "properties": {"account": OBJECT_SCHEMA},
}
PROFILE_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["profile"],
    "properties": {"profile": OBJECT_SCHEMA},
}


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


@route(
    "GET",
    "me",
    None,
    "Read the signed-in member account",
    ACCOUNT_RESPONSE_SCHEMA,
    authentication="session",
)
def get_me(request):
    return JsonResponse({"account": serialize_account(request.user)})


@route(
    "PATCH",
    "me",
    None,
    "Update the signed-in member account",
    ACCOUNT_RESPONSE_SCHEMA,
    OBJECT_SCHEMA,
    authentication="session",
)
def patch_me(request):
    try:
        account = update_account_settings(request.user, read_json_object(request))
    except AccountSettingsError as error:
        raise APIError(400, error.code, error.message, details=error.details) from error
    return JsonResponse({"account": account})


@route(
    "GET",
    "me/profile",
    None,
    "Read the signed-in member profile",
    PROFILE_RESPONSE_SCHEMA,
    authentication="session",
)
def get_me_profile(request):
    return _profile_response(request.user)


@route(
    "PATCH",
    "me/profile",
    None,
    "Update the signed-in member profile",
    PROFILE_RESPONSE_SCHEMA,
    OBJECT_SCHEMA,
    authentication="session",
    requires_if_match=True,
)
def patch_me_profile(request):
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


@route(
    "POST",
    "me/password",
    None,
    "Change the signed-in member password",
    OBJECT_SCHEMA,
    OBJECT_SCHEMA,
    authentication="session",
)
def post_me_password(request):
    values = read_json_object(request)
    unknown = set(values) - {"current_password", "new_password"}
    if unknown:
        raise APIError(
            400,
            "unknown_fields",
            "Request contains fields that cannot be changed.",
            details={"fields": sorted(unknown)},
        )
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


@route(
    "GET",
    "me/data-export",
    None,
    "Export the signed-in member data",
    OBJECT_SCHEMA,
    authentication="session",
)
def get_me_data_export(request):
    payload = build_user_data_export(request.user)
    write_export_log(request.user)
    response = JsonResponse(payload, json_dumps_params={"indent": 2, "sort_keys": True})
    response["Content-Disposition"] = 'attachment; filename="community-account-data.json"'
    return response


@route(
    "POST",
    "me/deletion-request",
    None,
    "Request deletion of the signed-in member account",
    OBJECT_SCHEMA,
    OBJECT_SCHEMA,
    authentication="session",
)
def post_me_deletion_request(request):
    read_json_object(request)
    deletion_request, created = request_account_deletion(request.user)
    return JsonResponse(
        {
            "status": deletion_request.status,
            "request_id": deletion_request.pk,
            "created": created,
        },
        status=201 if created else 200,
    )
