import datetime
import hashlib
import json

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
from community_base.accounts.models import EmailAlias
from community_base.accounts.return_urls import safe_return_path
from community_base.accounts.tokens import (
    ActionTokenError,
    generate_password_reset_token,
    generate_verification_token,
    load_password_reset_token,
    load_verification_token,
    password_reset_token_matches,
)
from community_base.kernel.conf import get
from community_base.mail import send as send_mail

AUTH_BACKEND = f"{ModelBackend.__module__}.{ModelBackend.__name__}"
INVALID_LOGIN = "Invalid email or password"


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _site_url(path):
    return f"{get('SITE_URL').rstrip('/')}{path}"


def _mail_key(purpose, user, token):
    fingerprint = hashlib.sha256(token.encode()).hexdigest()[:24]
    return f"accounts:{purpose}:{user.pk}:{fingerprint}"


def _queue_verification(user, return_path=""):
    token = generate_verification_token(user, return_path=return_path)
    send_mail(
        "accounts.verify_email",
        user.email,
        {"verify_url": _site_url(f"/accounts/verify/?token={token}")},
        _mail_key("verify", user, token),
        user=user,
    )
    return token


def _queue_password_reset(user):
    token = generate_password_reset_token(user)
    send_mail(
        "accounts.password_reset",
        user.email,
        {"reset_url": _site_url(f"/accounts/password-reset/?token={token}")},
        _mail_key("password-reset", user, token),
        user=user,
    )
    return token


def _resolve_active_user(email):
    User = get_user_model()
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is not None:
        return user
    alias = (
        EmailAlias.objects.select_related("user")
        .filter(email__iexact=email, user__is_active=True)
        .first()
    )
    return alias.user if alias else None


def _authenticate(email, password):
    User = get_user_model()
    user = _resolve_active_user(email)
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
            verification_expires_at=timezone.now() + datetime.timedelta(days=7),
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
    return render(request, "accounts/login.html", {"form": form, "next": next_path})


def register_view(request):
    next_path = safe_return_path(request.GET.get("next") or request.POST.get("next"), "/")
    if request.user.is_authenticated:
        return redirect(next_path)
    form = RegistrationForm(request.POST or None, initial={"next": next_path})
    if request.method == "POST" and form.is_valid():
        user, _token = _create_user(form)
        login(request, user, backend=AUTH_BACKEND)
        return redirect("accounts:verification_sent")
    return render(request, "accounts/register.html", {"form": form, "next": next_path})


def logout_view(request):
    logout(request)
    return redirect(safe_return_path(request.GET.get("next"), "/"))


def verification_sent_view(request):
    return _private(render(request, "accounts/verification_sent.html"))


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
        user = _resolve_active_user(form.cleaned_data["email"])
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
        return redirect("accounts:password_reset_complete")
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
    user = _resolve_active_user(email)
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
    user = _resolve_active_user(form.cleaned_data["email"])
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
