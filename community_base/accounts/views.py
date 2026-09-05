import datetime
import hashlib
import json
import uuid
from urllib.parse import urlencode

from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.backends import ModelBackend
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from community_base.accounts.forms import (
    LoginForm,
    PasswordResetForm,
    PasswordResetRequestForm,
    RegistrationForm,
)
from community_base.accounts.oauth import provider_context
from community_base.accounts.return_urls import safe_return_path
from community_base.accounts.services.email_resolution import resolve_user_by_email
from community_base.accounts.services.verification import unverified_user_ttl_days
from community_base.accounts.tokens import (
    ActionTokenError,
    load_password_reset_token,
    load_verification_token,
    password_reset_token_matches,
)
from community_base.mail import send as send_mail

AUTH_BACKEND = f"{ModelBackend.__module__}.{ModelBackend.__name__}"
INVALID_LOGIN = "Invalid email or password"


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _mail_key(purpose, user, nonce):
    fingerprint = hashlib.sha256(str(nonce).encode()).hexdigest()[:24]
    return f"accounts:{purpose}:{user.pk}:{fingerprint}"


def _queue_verification(user, return_path=""):
    nonce = uuid.uuid4()
    send_mail(
        "accounts.verify_email",
        user.email,
        {"return_path": return_path} if return_path else {},
        _mail_key("verify", user, nonce),
        user=user,
    )
    return nonce


def _queue_password_reset(user):
    nonce = uuid.uuid4()
    send_mail(
        "accounts.password_reset",
        user.email,
        {},
        _mail_key("password-reset", user, nonce),
        user=user,
    )
    return nonce


def _authenticate(email, password):
    User = get_user_model()
    user = resolve_user_by_email(email)
    if user is not None and user.has_usable_password() and user.check_password(password):
        return user
    if user is None or not user.has_usable_password():
        User().set_password(password)
    return None


def _create_user(form):
    with transaction.atomic():
        user = get_user_model().objects.create_user(
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
            signup_source="signup",
            verification_expires_at=timezone.now()
            + datetime.timedelta(days=unverified_user_ttl_days()),
        )
        token = _queue_verification(user, form.cleaned_data.get("next", ""))
    return user, token


def login_view(request):
    next_path = safe_return_path(request.GET.get("next") or request.POST.get("next"), "/")
    if request.user.is_authenticated:
        return redirect(next_path)
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = _authenticate(form.cleaned_data["email"], form.cleaned_data["password"])
        if user is not None:
            login(request, user, backend=AUTH_BACKEND)
            return redirect(next_path)
        form.add_error(None, INVALID_LOGIN)
    context = {"form": form, "next": next_path, **provider_context()}
    return render(request, "accounts/login.html", context)


def register_view(request):
    next_path = safe_return_path(request.GET.get("next") or request.POST.get("next"), "/")
    if request.user.is_authenticated:
        return redirect(next_path)
    form = RegistrationForm(request.POST or None, initial={"next": next_path})
    if request.method == "POST" and form.is_valid():
        user, _token = _create_user(form)
        login(request, user, backend=AUTH_BACKEND)
        return redirect("account_verification_sent")
    context = {"form": form, "next": next_path, **provider_context()}
    return render(request, "accounts/register.html", context)


def signup_redirect_view(request):
    next_path = safe_return_path(request.GET.get("next"), "")
    target = "/accounts/register/"
    if next_path:
        target = f"{target}?{urlencode({'next': next_path})}"
    return redirect(target)


def logout_view(request):
    logout(request)
    return redirect(safe_return_path(request.GET.get("next"), "/"))


def verification_sent_view(request):
    return _private(render(request, "accounts/verification_sent.html"))


def resend_verification_view(request):
    initial_email = request.user.email if request.user.is_authenticated else ""
    form = PasswordResetRequestForm(
        request.POST or None,
        initial={"email": initial_email},
    )
    if request.method == "POST" and form.is_valid():
        user = resolve_user_by_email(form.cleaned_data["email"])
        if user is not None and not user.email_verified:
            with transaction.atomic():
                _queue_verification(user)
        return redirect("account_verification_sent")
    return _private(render(request, "accounts/resend_verification.html", {"form": form}))


def verify_email_view(request):
    token = request.GET.get("token", "")
    try:
        payload = load_verification_token(token)
        user = get_user_model().objects.get(pk=payload["user_id"], email__iexact=payload["email"])
    except ActionTokenError as error:
        message = (
            "This verification link has expired."
            if error.code == "expired"
            else "This verification link is invalid."
        )
        return _private(
            render(
                request,
                "accounts/verification_result.html",
                {"success": False, "message": message},
                status=400,
            )
        )
    except get_user_model().DoesNotExist:
        return _private(
            render(
                request,
                "accounts/verification_result.html",
                {"success": False, "message": "This account no longer exists."},
                status=404,
            )
        )

    fields = []
    if not user.email_verified:
        user.email_verified = True
        fields.append("email_verified")
    if user.verification_expires_at is not None:
        user.verification_expires_at = None
        fields.append("verification_expires_at")
    if user.signup_source == "signup" and not user.account_activated:
        user.account_activated = True
        fields.append("account_activated")
    if fields:
        user.save(update_fields=fields)
    return_path = safe_return_path(payload.get("return_path"), "")
    if return_path:
        return _private(redirect(return_path))
    return _private(
        render(
            request,
            "accounts/verification_result.html",
            {"success": True, "message": "Your email address is verified."},
        )
    )


def password_reset_request_view(request):
    form = PasswordResetRequestForm(
        request.POST or None, initial={"email": request.GET.get("email", "")}
    )
    if request.method == "POST" and form.is_valid():
        user = resolve_user_by_email(form.cleaned_data["email"])
        if user is not None:
            with transaction.atomic():
                _queue_password_reset(user)
        return _private(render(request, "accounts/password_reset_sent.html"))
    return _private(render(request, "accounts/password_reset_request.html", {"form": form}))


def password_reset_view(request):
    token = request.GET.get("token") or request.POST.get("token", "")
    try:
        payload = load_password_reset_token(token)
        user = get_user_model().objects.get(pk=payload["user_id"], is_active=True)
        if not password_reset_token_matches(user, payload):
            raise ActionTokenError("invalid")
    except (ActionTokenError, get_user_model().DoesNotExist):
        return _private(
            render(
                request,
                "accounts/password_reset.html",
                {"error": "This password reset link is invalid or expired."},
                status=400,
            )
        )
    form = PasswordResetForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        user.set_password(form.cleaned_data["new_password"])
        if not user.account_activated:
            user.account_activated = True
            user.save(update_fields=["password", "account_activated"])
        else:
            user.save(update_fields=["password"])
        return redirect("account_password_reset_complete")
    return _private(
        render(
            request,
            "accounts/password_reset.html",
            {"form": form, "token": token, "reset_email": user.email},
        )
    )


def password_reset_complete_view(request):
    return _private(render(request, "accounts/password_reset_complete.html"))


def _json(request):
    try:
        value = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


@require_POST
def register_api(request):
    data = _json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    form = RegistrationForm(
        {
            "email": data.get("email", ""),
            "password": data.get("password", ""),
            "next": safe_return_path(data.get("next"), ""),
        }
    )
    if not form.is_valid():
        return JsonResponse({"error": next(iter(form.errors.values()))[0]}, status=400)
    user, _token = _create_user(form)
    login(request, user, backend=AUTH_BACKEND)
    return JsonResponse(
        {"status": "ok", "redirect_url": safe_return_path(data.get("next"), "/")}, status=201
    )


@require_POST
def login_api(request):
    data = _json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    form = LoginForm(data)
    if not form.is_valid():
        return JsonResponse({"error": "Email and password are required"}, status=400)
    user = _authenticate(form.cleaned_data["email"], form.cleaned_data["password"])
    if user is None:
        return JsonResponse({"error": INVALID_LOGIN}, status=401)
    login(request, user, backend=AUTH_BACKEND)
    return JsonResponse({"status": "ok", "redirect_url": safe_return_path(data.get("next"), "/")})


@require_POST
def resend_verification_api(request):
    data = _json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    email = str(data.get("email", "")).strip().lower()
    user = resolve_user_by_email(email)
    if user is not None and not user.email_verified:
        with transaction.atomic():
            _queue_verification(user, safe_return_path(data.get("next"), ""))
    return JsonResponse({"status": "ok"})


@require_POST
def password_reset_request_api(request):
    data = _json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    form = PasswordResetRequestForm({"email": data.get("email", "")})
    if not form.is_valid():
        return JsonResponse({"error": "Email is required"}, status=400)
    user = resolve_user_by_email(form.cleaned_data["email"])
    if user is not None:
        with transaction.atomic():
            _queue_password_reset(user)
    return JsonResponse(
        {
            "status": "ok",
            "message": (
                "If an account exists for that email, password reset instructions have been sent."
            ),
        }
    )


def password_reset_api(request):
    if request.method == "GET":
        return password_reset_view(request)
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    data = _json(request)
    if data is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    token = data.get("token", "")
    try:
        payload = load_password_reset_token(token)
        user = get_user_model().objects.get(pk=payload["user_id"], is_active=True)
        if not password_reset_token_matches(user, payload):
            raise ActionTokenError("invalid")
    except (ActionTokenError, get_user_model().DoesNotExist):
        return JsonResponse({"error": "Invalid or expired token"}, status=400)
    form = PasswordResetForm({"new_password": data.get("new_password", "")}, user=user)
    if not form.is_valid():
        return JsonResponse({"error": next(iter(form.errors.values()))[0]}, status=400)
    user.set_password(form.cleaned_data["new_password"])
    user.account_activated = True
    user.save(update_fields=["password", "account_activated"])
    return JsonResponse({"status": "ok"})
