import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from community_base.accounts.services.timezones import is_valid_timezone

_PREFERENCE_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_DISMISSAL_KEY = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,99}$")
ACCOUNT_FIELDS = {
    "first_name",
    "last_name",
    "email_preferences",
    "preferred_timezone",
    "theme_preference",
    "dismiss_card",
}


class AccountSettingsError(ValueError):
    def __init__(self, code, message, *, details=None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def serialize_account(user):
    return {
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


def _validated_preferences(value):
    if not isinstance(value, dict):
        raise AccountSettingsError(
            "invalid_email_preferences",
            "Email preferences must be an object of boolean values.",
        )
    invalid = [
        key
        for key, enabled in value.items()
        if not isinstance(key, str)
        or _PREFERENCE_KEY.fullmatch(key) is None
        or not isinstance(enabled, bool)
    ]
    if invalid:
        raise AccountSettingsError(
            "invalid_email_preferences",
            "Email preference names must be safe keys with boolean values.",
            details={"fields": sorted(str(key) for key in invalid)},
        )
    return value


def update_account_settings(user, values):
    unknown = set(values) - ACCOUNT_FIELDS
    if unknown:
        raise AccountSettingsError(
            "unknown_fields",
            "Request contains fields that cannot be changed.",
            details={"fields": sorted(unknown)},
        )
    if not values:
        raise AccountSettingsError("empty_update", "At least one account field is required.")

    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        changed = set()
        for name in ("first_name", "last_name"):
            if name not in values:
                continue
            value = values[name]
            if not isinstance(value, str) or len(value.strip()) > 150:
                raise AccountSettingsError(
                    "invalid_name",
                    "Names must be strings of at most 150 characters.",
                    details={"field": name},
                )
            normalized = value.strip()
            if getattr(locked, name) != normalized:
                setattr(locked, name, normalized)
                changed.add(name)

        if "email_preferences" in values:
            preferences = dict(locked.email_preferences or {})
            incoming = _validated_preferences(values["email_preferences"])
            preferences.update(incoming)
            if preferences != locked.email_preferences:
                locked.email_preferences = preferences
                changed.add("email_preferences")
            if "newsletter" in incoming and locked.unsubscribed == incoming["newsletter"]:
                locked.unsubscribed = not incoming["newsletter"]
                changed.add("unsubscribed")

        if "preferred_timezone" in values:
            timezone_name = values["preferred_timezone"]
            if not isinstance(timezone_name, str):
                raise AccountSettingsError("invalid_timezone", "Timezone must be a string.")
            timezone_name = timezone_name.strip()
            if timezone_name and not is_valid_timezone(timezone_name):
                raise AccountSettingsError(
                    "invalid_timezone", "Timezone must be a valid IANA name."
                )
            if locked.preferred_timezone != timezone_name:
                locked.preferred_timezone = timezone_name
                changed.add("preferred_timezone")

        if "theme_preference" in values:
            theme = values["theme_preference"]
            if theme not in ("", "light", "dark"):
                raise AccountSettingsError(
                    "invalid_theme", "Theme must be light, dark, or an empty string."
                )
            if locked.theme_preference != theme:
                locked.theme_preference = theme
                changed.add("theme_preference")

        if "dismiss_card" in values:
            card = values["dismiss_card"]
            if not isinstance(card, str) or _DISMISSAL_KEY.fullmatch(card) is None:
                raise AccountSettingsError(
                    "invalid_dismissal", "Dismissal key contains unsupported characters."
                )
            dismissals = list(locked.dashboard_dismissals or [])
            if card not in dismissals:
                dismissals.append(card)
                locked.dashboard_dismissals = dismissals
                changed.add("dashboard_dismissals")

        if changed:
            try:
                locked.full_clean(exclude=("password",))
            except ValidationError as error:
                raise AccountSettingsError(
                    "invalid_account", "Account values are invalid."
                ) from error
            locked.save(update_fields=sorted(changed))
    return serialize_account(locked)
