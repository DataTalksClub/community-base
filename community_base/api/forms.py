from __future__ import annotations

import re

from django import forms
from django.contrib.auth import get_user_model

from community_base.api.models import APIKey

_SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


class APIKeyCreateForm(forms.Form):
    user = forms.ModelChoiceField(queryset=None)
    name = forms.CharField(max_length=120)
    kind = forms.ChoiceField(choices=APIKey.Kind.choices)
    scopes = forms.CharField(
        help_text="Comma-separated scopes. Use * only for deliberately unrestricted keys."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            get_user_model().objects.filter(is_active=True).order_by("pk")
        )

    def clean_scopes(self) -> list[str]:
        scopes = sorted(
            {part.strip() for part in self.cleaned_data["scopes"].split(",") if part.strip()}
        )
        if not scopes:
            raise forms.ValidationError("At least one scope is required.")
        invalid = next(
            (scope for scope in scopes if scope != "*" and not _SCOPE_RE.fullmatch(scope)), None
        )
        if invalid:
            raise forms.ValidationError(f"Invalid scope: {invalid}")
        return scopes

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get("user")
        if cleaned.get("kind") == APIKey.Kind.STAFF and user is not None and not user.is_staff:
            self.add_error("user", "Staff API keys require a staff user.")
        return cleaned
