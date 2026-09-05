from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from community_base.accounts.models import MemberProfile

PROFILE_COMPLETION_VERSION = 1
PROFILE_FIELDS = (
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
)
PROFILE_REQUIRED_FIELDS = (
    "country",
    "work_status",
    "professional_role",
    "seniority",
    "about",
    "ambitions",
    "why_joined",
)


class ProfileUpdateError(ValueError):
    def __init__(self, code, message, *, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ProfileState:
    profile: MemberProfile | None
    data: dict


def _missing_fields(profile):
    return [name for name in PROFILE_REQUIRED_FIELDS if not getattr(profile, name, "")]


def serialize_profile(user, profile=None):
    if profile is None:
        profile = MemberProfile.objects.filter(user=user).first()
    values = {name: getattr(profile, name, "") for name in PROFILE_FIELDS}
    revision = profile.revision if profile is not None else 0
    values.update(
        {
            "id": str(profile.pk) if profile is not None else None,
            "required_fields": list(PROFILE_REQUIRED_FIELDS),
            "missing_fields": _missing_fields(profile),
            "completion_version": profile.completion_version if profile is not None else 0,
            "completed_at": (
                profile.completed_at.isoformat()
                if profile is not None and profile.completed_at is not None
                else None
            ),
            "revision": revision,
            "confirmed_revision": profile.confirmed_revision if profile is not None else 0,
        }
    )
    return values


def _validation_details(error):
    if hasattr(error, "message_dict"):
        return {
            field: [str(message) for message in messages]
            for field, messages in error.message_dict.items()
        }
    return {"profile": [str(message) for message in error.messages]}


def update_profile(user, values, *, expected_revision):
    unknown = set(values) - set(PROFILE_FIELDS)
    if unknown:
        raise ProfileUpdateError(
            "unknown_fields",
            "Request contains fields that cannot be changed.",
            details={"fields": sorted(unknown)},
        )
    invalid_types = [name for name, value in values.items() if not isinstance(value, str)]
    if invalid_types:
        raise ProfileUpdateError(
            "invalid_fields",
            "Profile fields must be strings.",
            details={"fields": sorted(invalid_types)},
        )

    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        profile = MemberProfile.objects.select_for_update().filter(user=locked_user).first()
        current_revision = profile.revision if profile is not None else 0
        if expected_revision != current_revision:
            raise ProfileUpdateError(
                "revision_conflict",
                "The profile changed after it was read.",
                details={"current_revision": current_revision},
            )
        if profile is None:
            profile = MemberProfile(user=locked_user)

        for name, value in values.items():
            normalized = value.strip() if name != "country" else value.strip().upper()
            setattr(profile, name, normalized)

        missing = _missing_fields(profile)
        if profile.completion_version >= PROFILE_COMPLETION_VERSION and missing:
            raise ProfileUpdateError(
                "required_fields_missing",
                "A completed profile cannot clear required fields.",
                details={"fields": missing},
            )
        try:
            profile.full_clean()
        except ValidationError as error:
            raise ProfileUpdateError(
                "invalid_profile",
                "Profile values are invalid.",
                details=_validation_details(error),
            ) from error

        profile.revision = current_revision + 1
        profile.confirmed_revision = profile.revision
        if not missing and locked_user.email_verified:
            if profile.completion_version < PROFILE_COMPLETION_VERSION:
                profile.completion_version = PROFILE_COMPLETION_VERSION
                profile.completed_at = timezone.now()
        profile.save()
    return ProfileState(profile, serialize_profile(locked_user, profile))
