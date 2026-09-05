import secrets
from dataclasses import dataclass
from datetime import timedelta

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from community_base.accounts.models import EmailAlias, EmailChangeRequest
from community_base.accounts.services.email_resolution import normalize_email
from community_base.mail import send

EMAIL_CHANGE_TOKEN_SALT = "community-base.accounts.email-change"


class EmailChangeError(ValueError):
    code = "email_change_error"

    def __init__(self, message="We could not change that email address."):
        self.message = message
        super().__init__(message)


class InvalidPassword(EmailChangeError):
    code = "invalid_password"


class EmailUnavailable(EmailChangeError):
    code = "email_unavailable"


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    status: str
    user: object | None = None
    old_email: str = ""
    new_email: str = ""

    @property
    def success(self):
        return self.status == "confirmed"


def email_change_token(change):
    return signing.dumps(
        {"id": change.pk, "nonce": change.token_hash},
        salt=EMAIL_CHANGE_TOKEN_SALT,
        compress=True,
    )


def _available(user, email):
    User = get_user_model()
    primary_exists = User.objects.filter(email__iexact=email, is_active=True).exclude(pk=user.pk)
    alias = EmailAlias.objects.filter(email__iexact=email).exclude(user=user)
    return not primary_exists.exists() and not alias.exists()


def _validate_email(user, raw_email):
    email = normalize_email(raw_email)
    try:
        validate_email(email)
    except ValidationError as error:
        raise EmailUnavailable("Enter a valid email address.") from error
    if email == normalize_email(user.email):
        raise EmailUnavailable("Enter a different email address.")
    if not _available(user, email):
        raise EmailUnavailable("That email cannot be used for this account.")
    return email


def request_email_change(user, new_email, current_password=None):
    if user.has_usable_password() and not user.check_password(current_password or ""):
        raise InvalidPassword("Enter your current password.")
    normalized = _validate_email(user, new_email)
    now = timezone.now()
    with transaction.atomic():
        EmailChangeRequest.objects.filter(
            user=user,
            confirmed_at__isnull=True,
            invalidated_at__isnull=True,
        ).update(invalidated_at=now)
        change = EmailChangeRequest.objects.create(
            user=user,
            old_email=normalize_email(user.email),
            new_email=normalized,
            token_hash=secrets.token_hex(32),
            expires_at=now + timedelta(hours=24),
            last_sent_at=now,
        )
        send(
            "accounts.email_change_confirm",
            normalized,
            {
                "old_email": change.old_email,
                "new_email": normalized,
                "change_request_id": change.pk,
                "expiry_hours": 24,
            },
            f"accounts:email-change-confirm:{change.pk}",
            user=user,
            related=change,
        )
        token = email_change_token(change)
    return change, token


def _sync_allauth(user, old_email, new_email):
    EmailAddress.objects.filter(user=user, primary=True).update(primary=False)
    record, _created = EmailAddress.objects.get_or_create(
        user=user,
        email=new_email,
        defaults={"verified": True, "primary": True},
    )
    changed = []
    if not record.verified:
        record.verified = True
        changed.append("verified")
    if not record.primary:
        record.primary = True
        changed.append("primary")
    if changed:
        record.save(update_fields=changed)
    EmailAddress.objects.filter(user=user, email__iexact=old_email).exclude(pk=record.pk).update(
        primary=False
    )


def confirm_email_change(token):
    try:
        payload = signing.loads(
            (token or "").strip(),
            salt=EMAIL_CHANGE_TOKEN_SALT,
            max_age=24 * 60 * 60,
        )
        change_id = payload["id"]
        nonce = payload["nonce"]
    except (signing.BadSignature, KeyError, TypeError):
        return ConfirmationResult("invalid")
    now = timezone.now()
    with transaction.atomic():
        change = (
            EmailChangeRequest.objects.select_for_update()
            .select_related("user")
            .filter(pk=change_id, token_hash=nonce)
            .first()
        )
        if change is None:
            return ConfirmationResult("invalid")
        if change.confirmed_at is not None:
            return ConfirmationResult("reused")
        if change.invalidated_at is not None:
            return ConfirmationResult("superseded")
        if change.expires_at <= now:
            return ConfirmationResult("expired")
        user = get_user_model().objects.select_for_update().get(pk=change.user_id)
        if not _available(user, change.new_email):
            return ConfirmationResult("collision")
        old_email = change.old_email
        EmailAlias.objects.filter(user=user, email__iexact=change.new_email).delete()
        user.email = change.new_email
        user.email_verified = True
        user.verification_expires_at = None
        user.slack_checked_at = None
        try:
            user.save(
                update_fields=(
                    "email",
                    "email_verified",
                    "verification_expires_at",
                    "slack_checked_at",
                )
            )
            _sync_allauth(user, old_email, change.new_email)
            EmailAlias.objects.get_or_create(
                email=old_email,
                defaults={
                    "user": user,
                    "source": EmailAlias.Source.ACCOUNT_CHANGE,
                    "note": "Former login email retained after account change.",
                },
            )
        except IntegrityError:
            transaction.set_rollback(True)
            return ConfirmationResult("collision")
        change.confirmed_at = now
        change.save(update_fields=["confirmed_at"])
        send(
            "accounts.email_changed_notice",
            old_email,
            {"old_email": old_email, "new_email": change.new_email},
            f"accounts:email-changed-notice:{change.pk}",
            user=user,
            related=change,
        )
    return ConfirmationResult("confirmed", user, old_email, change.new_email)
