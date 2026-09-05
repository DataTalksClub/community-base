from dataclasses import dataclass

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from django.utils.crypto import salted_hmac

from community_base.accounts.models import PrivacyRequestLog
from community_base.accounts.services.email_resolution import normalize_email
from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _optional_model(label, name):
    try:
        return apps.get_model(label, name)
    except LookupError:
        return None


def build_user_data_export(user):
    excluded = {
        "password",
        "groups",
        "user_permissions",
        "verification_resend_claim_token",
    }
    account = {
        field.name: _plain(getattr(user, field.name))
        for field in user._meta.concrete_fields
        if field.name not in excluded
    }
    export = {
        "generated_at": timezone.now().isoformat(),
        "account": account,
        "email_aliases": list(user.email_aliases.values("email", "source", "note", "created_at")),
        "member_profile": None,
        "social_accounts": [],
        "api_keys": [],
        "member_notes": [],
        "mail_deliveries": [],
        "notifications": [],
        "notification_preferences": [],
    }
    profile = getattr(user, "member_profile", None)
    if profile is not None:
        export["member_profile"] = model_to_dict(profile, exclude=("user",))
    social = _optional_model("socialaccount", "SocialAccount")
    if social is not None:
        export["social_accounts"] = list(
            social.objects.filter(user=user).values("provider", "uid", "date_joined", "last_login")
        )
    api_key = _optional_model("cb_api", "APIKey")
    if api_key is not None:
        export["api_keys"] = list(
            api_key.objects.filter(user=user).values(
                "id", "name", "scopes", "kind", "created_at", "last_used_at", "revoked_at"
            )
        )
    note = _optional_model("cb_studio", "MemberNote")
    if note is not None:
        export["member_notes"] = list(
            note.objects.filter(member=user).values(
                "visibility", "kind", "body", "tags", "created_at", "updated_at"
            )
        )
    delivery = _optional_model("cb_mail", "EmailDelivery")
    if delivery is not None:
        export["mail_deliveries"] = list(
            delivery.objects.filter(recipient_user=user).values(
                "id", "purpose", "category", "state", "reason_code", "created_at", "updated_at"
            )
        )
    notification = _optional_model("notifications", "Notification")
    if notification is not None:
        export["notifications"] = list(
            notification.objects.filter(user=user).values(
                "id",
                "title",
                "body",
                "url",
                "notification_type",
                "source_key",
                "source_id",
                "read",
                "read_at",
                "created_at",
            )
        )
    preference = _optional_model("notifications", "NotificationPreference")
    if preference is not None:
        export["notification_preferences"] = list(
            preference.objects.filter(user=user).values(
                "source_key", "enabled", "created_at", "updated_at"
            )
        )
    hook = get("ACCOUNT_PRIVACY_EXPORT_HOOK")
    if hook is not None:
        extra = (resolve(hook) if isinstance(hook, str) else hook)(user=user)
        if not isinstance(extra, dict):
            raise TypeError("ACCOUNT_PRIVACY_EXPORT_HOOK must return a dictionary")
        export["site_data"] = extra
    return _plain(export)


def _email_audit_values(email):
    normalized = normalize_email(email)
    digest = salted_hmac("community-base-privacy-email", normalized).hexdigest()
    domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
    return digest, domain


def write_export_log(user):
    digest, domain = _email_audit_values(user.email)
    return PrivacyRequestLog.objects.create(
        request_type=PrivacyRequestLog.RequestType.EXPORT,
        status=PrivacyRequestLog.Status.COMPLETED,
        old_user_id=user.pk,
        normalized_email_hash=digest,
        email_domain=domain,
    )


def request_account_deletion(user):
    digest, domain = _email_audit_values(user.email)
    active = {
        "old_user_id": user.pk,
        "request_type": PrivacyRequestLog.RequestType.DELETION_REQUEST,
        "status__in": (
            PrivacyRequestLog.Status.REQUESTED,
            PrivacyRequestLog.Status.PENDING_DELIVERY,
        ),
    }
    try:
        with transaction.atomic():
            existing = PrivacyRequestLog.objects.filter(**active).first()
            if existing is not None:
                return existing, False
            request = PrivacyRequestLog.objects.create(
                request_type=PrivacyRequestLog.RequestType.DELETION_REQUEST,
                status=PrivacyRequestLog.Status.REQUESTED,
                old_user_id=user.pk,
                normalized_email_hash=digest,
                email_domain=domain,
            )
    except IntegrityError:
        return PrivacyRequestLog.objects.get(**active), False
    return request, True


@dataclass(frozen=True, slots=True)
class DeletionResult:
    deleted: bool
    blocker_reason: str = ""
    row_count_summary: dict[str, int] | None = None


def _delete_sessions(user_id):
    deleted = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        if str(session.get_decoded().get("_auth_user_id", "")) == str(user_id):
            session.delete()
            deleted += 1
    return deleted


def delete_account_for_privacy(user):
    blocker = get("ACCOUNT_DELETION_BLOCKER")
    reason = (
        (resolve(blocker) if isinstance(blocker, str) else blocker)(user=user) if blocker else ""
    )
    digest, domain = _email_audit_values(user.email)
    if reason:
        PrivacyRequestLog.objects.create(
            request_type=PrivacyRequestLog.RequestType.DELETE,
            status=PrivacyRequestLog.Status.BLOCKED,
            old_user_id=user.pk,
            normalized_email_hash=digest,
            email_domain=domain,
            blocker_reason=str(reason)[:64],
        )
        return DeletionResult(False, str(reason)[:64], {})

    user_id = user.pk
    summary = {}
    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user_id)
        before_delete = get("ACCOUNT_BEFORE_DELETE_HOOK")
        if before_delete is not None:
            extra = (resolve(before_delete) if isinstance(before_delete, str) else before_delete)(
                user=locked
            )
            if extra is not None:
                if not isinstance(extra, dict):
                    raise TypeError("ACCOUNT_BEFORE_DELETE_HOOK must return a dictionary or None")
                summary.update({str(key): int(value) for key, value in extra.items()})
        summary["sessions"] = _delete_sessions(user_id)
        delivery = _optional_model("cb_mail", "EmailDelivery")
        if delivery is not None:
            deliveries = delivery.objects.filter(recipient_user=locked)
            summary["mail_deliveries"] = deliveries.count()
            for row in deliveries.only("id"):
                delivery.objects.filter(pk=row.pk).update(
                    recipient_user=None,
                    recipient_email=f"deleted+{row.pk}@deleted.invalid",
                    context_data={},
                    transport_options={},
                )
        PrivacyRequestLog.objects.filter(
            old_user_id=user_id,
            request_type=PrivacyRequestLog.RequestType.DELETION_REQUEST,
            status__in=(
                PrivacyRequestLog.Status.REQUESTED,
                PrivacyRequestLog.Status.PENDING_DELIVERY,
            ),
        ).update(status=PrivacyRequestLog.Status.COMPLETED)
        _deleted_count, deleted_by_model = locked.delete()
        summary.update(
            {
                label: count
                for label, count in deleted_by_model.items()
                if count and label != "accounts.User"
            }
        )
        PrivacyRequestLog.objects.create(
            request_type=PrivacyRequestLog.RequestType.DELETE,
            status=PrivacyRequestLog.Status.COMPLETED,
            old_user_id=user_id,
            normalized_email_hash=digest,
            email_domain=domain,
            row_count_summary=summary,
        )
    return DeletionResult(True, row_count_summary=summary)
