from dataclasses import asdict, dataclass, field

from django.apps import apps
from django.db import transaction
from django.utils import timezone

from community_base.accounts.models import EmailAlias, EmailChangeRequest, MemberProfile
from community_base.accounts.services.email_resolution import normalize_email
from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve

SCRUBBED_EMAIL_SUFFIX = "@merged.invalid"
BOUNCE_RANK = {"none": 0, "soft": 1, "permanent": 2}


class MergeError(ValueError):
    pass


@dataclass(slots=True)
class MergePlan:
    canonical_id: int
    secondary_id: int
    dry_run: bool
    alias: str = ""
    relations_moved: dict[str, int] = field(default_factory=dict)
    scalar_changes: list[str] = field(default_factory=list)
    secondary_deactivated: bool = False
    already_merged: bool = False

    def to_dict(self):
        return asdict(self)


def _model(label, name):
    try:
        return apps.get_model(label, name)
    except LookupError:
        return None


def _move_queryset(plan, label, name, field_name, secondary, canonical):
    model = _model(label, name)
    if model is None:
        return
    count = model.objects.filter(**{field_name: secondary}).update(**{field_name: canonical})
    if count:
        plan.relations_moved[f"{label}.{name}.{field_name}"] = count


def _revoke_and_move_api_keys(plan, secondary, canonical):
    model = _model("cb_api", "APIKey")
    if model is None:
        return
    queryset = model.objects.filter(user=secondary)
    queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
    count = queryset.update(user=canonical)
    if count:
        plan.relations_moved["cb_api.APIKey.user"] = count


def _merge_profile(plan, canonical, secondary):
    secondary_profile = MemberProfile.objects.filter(user=secondary).first()
    if secondary_profile is None:
        return
    canonical_profile = MemberProfile.objects.filter(user=canonical).first()
    if canonical_profile is None:
        secondary_profile.user = canonical
        secondary_profile.save(update_fields=["user"])
        plan.relations_moved["accounts.MemberProfile.user"] = 1
        return
    changed = []
    for field_name in (
        "country",
        "work_status",
        "organisation",
        "professional_role",
        "seniority",
        "about",
        "ambitions",
        "why_joined",
        "github_url",
        "linkedin_url",
        "website_url",
    ):
        if not getattr(canonical_profile, field_name) and getattr(secondary_profile, field_name):
            setattr(canonical_profile, field_name, getattr(secondary_profile, field_name))
            changed.append(field_name)
    if secondary_profile.completion_version > canonical_profile.completion_version:
        canonical_profile.completion_version = secondary_profile.completion_version
        canonical_profile.completed_at = secondary_profile.completed_at
        changed.extend(("completion_version", "completed_at"))
    if changed:
        canonical_profile.revision += 1
        changed.append("revision")
        canonical_profile.save(update_fields=changed)
    secondary_profile.delete()


def _merge_email_addresses(plan, canonical, secondary):
    model = _model("account", "EmailAddress")
    if model is None:
        return
    canonical_emails = {
        normalize_email(email)
        for email in model.objects.filter(user=canonical).values_list("email", flat=True)
    }
    moved = 0
    for address in model.objects.filter(user=secondary):
        if normalize_email(address.email) in canonical_emails:
            address.delete()
            continue
        address.user = canonical
        address.primary = False
        address.save(update_fields=["user", "primary"])
        moved += 1
    if moved:
        plan.relations_moved["account.EmailAddress.user"] = moved


def _merge_scalars(plan, canonical, secondary):
    changed = set()
    for name in ("email_verified", "account_activated", "slack_member"):
        if getattr(secondary, name) and not getattr(canonical, name):
            setattr(canonical, name, True)
            changed.add(name)
    for name in ("first_name", "last_name", "preferred_timezone", "theme_preference"):
        if not getattr(canonical, name) and getattr(secondary, name):
            setattr(canonical, name, getattr(secondary, name))
            changed.add(name)
    if not canonical.slack_user_id and secondary.slack_user_id:
        canonical.slack_user_id = secondary.slack_user_id
        canonical.slack_checked_at = secondary.slack_checked_at
        changed.update(("slack_user_id", "slack_checked_at"))
    tags = list(dict.fromkeys([*(canonical.tags or []), *(secondary.tags or [])]))
    if tags != canonical.tags:
        canonical.tags = tags
        changed.add("tags")
    dismissals = list(
        dict.fromkeys(
            [*(canonical.dashboard_dismissals or []), *(secondary.dashboard_dismissals or [])]
        )
    )
    if dismissals != canonical.dashboard_dismissals:
        canonical.dashboard_dismissals = dismissals
        changed.add("dashboard_dismissals")
    preferences = dict(secondary.email_preferences or {})
    for key, value in (canonical.email_preferences or {}).items():
        preferences[key] = value if key not in preferences else bool(value and preferences[key])
    if preferences != canonical.email_preferences:
        canonical.email_preferences = preferences
        changed.add("email_preferences")
    if secondary.unsubscribed and not canonical.unsubscribed:
        canonical.unsubscribed = True
        changed.add("unsubscribed")
    if BOUNCE_RANK.get(secondary.bounce_state, 0) > BOUNCE_RANK.get(canonical.bounce_state, 0):
        canonical.bounce_state = secondary.bounce_state
        canonical.bounce_recorded_at = secondary.bounce_recorded_at
        canonical.last_bounce_diagnostic = secondary.last_bounce_diagnostic
        changed.update(("bounce_state", "bounce_recorded_at", "last_bounce_diagnostic"))
    if secondary.soft_bounce_count > canonical.soft_bounce_count:
        canonical.soft_bounce_count = secondary.soft_bounce_count
        changed.add("soft_bounce_count")
    metadata = {**(secondary.import_metadata or {}), **(canonical.import_metadata or {})}
    if metadata != canonical.import_metadata:
        canonical.import_metadata = metadata
        changed.add("import_metadata")
    canonical.save(update_fields=sorted(changed)) if changed else None
    plan.scalar_changes.extend(sorted(changed))


def merge_accounts(canonical, secondary, *, actor=None, dry_run=False, force=False):
    plan = MergePlan(canonical.pk, secondary.pk, dry_run)
    with transaction.atomic():
        User = type(canonical)
        locked = {
            user.pk: user
            for user in User.objects.select_for_update().filter(pk__in=(canonical.pk, secondary.pk))
        }
        canonical, secondary = locked[canonical.pk], locked[secondary.pk]
        if canonical.pk == secondary.pk:
            raise MergeError("Cannot merge an account into itself.")
        if not secondary.is_active and secondary.email.endswith(SCRUBBED_EMAIL_SUFFIX):
            plan.already_merged = True
            return plan
        if not force and any(
            (canonical.is_staff, canonical.is_superuser, secondary.is_staff, secondary.is_superuser)
        ):
            raise MergeError("Staff accounts require force=True.")

        EmailChangeRequest.objects.filter(
            user__in=(canonical, secondary),
            confirmed_at__isnull=True,
            invalidated_at__isnull=True,
        ).update(invalidated_at=timezone.now())
        EmailChangeRequest.objects.filter(user=secondary).update(user=canonical)
        _merge_email_addresses(plan, canonical, secondary)
        _move_queryset(plan, "socialaccount", "SocialAccount", "user", secondary, canonical)
        _move_queryset(plan, "cb_mail", "EmailDelivery", "recipient_user", secondary, canonical)
        _move_queryset(plan, "cb_studio", "MemberNote", "member", secondary, canonical)
        _move_queryset(plan, "cb_studio", "MemberNote", "created_by", secondary, canonical)
        _move_queryset(plan, "accounts", "ImportBatch", "actor", secondary, canonical)
        _move_queryset(plan, "accounts", "EmailAlias", "user", secondary, canonical)
        _move_queryset(plan, "accounts", "EmailAlias", "created_by", secondary, canonical)
        _revoke_and_move_api_keys(plan, secondary, canonical)
        _merge_profile(plan, canonical, secondary)
        _merge_scalars(plan, canonical, secondary)
        canonical.groups.add(*secondary.groups.all())
        canonical.user_permissions.add(*secondary.user_permissions.all())
        hook = get("ACCOUNT_MERGE_HOOK")
        if hook is not None:
            (resolve(hook) if isinstance(hook, str) else hook)(
                canonical=canonical,
                secondary=secondary,
                plan=plan,
                dry_run=dry_run,
            )

        original_email = normalize_email(secondary.email)
        conflicting_alias = EmailAlias.objects.filter(email__iexact=original_email).exclude(
            user__in=(canonical, secondary)
        )
        conflicting_primary = User.objects.filter(email__iexact=original_email).exclude(
            pk__in=(canonical.pk, secondary.pk)
        )
        if conflicting_alias.exists() or conflicting_primary.exists():
            raise MergeError("The secondary email belongs to another account.")
        alias, _created = EmailAlias.objects.update_or_create(
            email=original_email,
            defaults={
                "user": canonical,
                "source": EmailAlias.Source.MERGE,
                "note": f"Merged user {secondary.pk} into {canonical.pk}.",
                "created_by": actor,
            },
        )
        plan.alias = alias.email
        secondary.email = f"merged+{secondary.pk}{SCRUBBED_EMAIL_SUFFIX}"
        secondary.is_active = False
        secondary.unsubscribed = True
        secondary.set_unusable_password()
        secondary.save(update_fields=["email", "is_active", "unsubscribed", "password"])
        plan.secondary_deactivated = True
        if dry_run:
            transaction.set_rollback(True)
    return plan
