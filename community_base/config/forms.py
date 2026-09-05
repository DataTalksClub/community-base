from __future__ import annotations

import json

from django import forms

from community_base.config.registry import Definition


class SettingsGroupForm(forms.Form):
    def __init__(self, *args, definitions: tuple[Definition, ...], initial_values: dict, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_definitions = definitions
        for item in definitions:
            self.fields[item.key] = self._field(item)
            if not item.secret:
                self.initial[item.key] = self._display_value(item, initial_values[item.key])

    @staticmethod
    def _field(item: Definition) -> forms.Field:
        common = {
            "label": item.label,
            "help_text": item.description,
            "required": not item.optional and not item.secret,
        }
        if item.value_type == "bool":
            return forms.BooleanField(**{**common, "required": False})
        if item.value_type == "int":
            return forms.IntegerField(**common)
        if item.value_type in {"json", "list"} or item.multiline:
            return forms.CharField(widget=forms.Textarea, **common)
        if item.is_email:
            return forms.EmailField(**common)
        if item.secret:
            return forms.CharField(
                widget=forms.PasswordInput(render_value=False),
                **{**common, "help_text": f"{item.description} Leave blank to keep it unchanged."},
            )
        return forms.CharField(**common)

    @staticmethod
    def _display_value(item: Definition, value):
        if item.value_type in {"json", "list"}:
            return json.dumps(value, indent=2, sort_keys=True)
        return value

    def cleaned_updates(self) -> dict:
        updates = {}
        for item in self.config_definitions:
            value = self.cleaned_data[item.key]
            if item.secret and not value:
                continue
            updates[item.key] = item.coerce(value)
        return updates


class SettingsImportForm(forms.Form):
    payload = forms.CharField(widget=forms.Textarea, help_text="Paste a settings export object.")
    reason = forms.CharField(max_length=500, required=False)

    def clean_payload(self):
        try:
            payload = json.loads(self.cleaned_data["payload"])
        except json.JSONDecodeError as error:
            raise forms.ValidationError("Payload must be valid JSON.") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("settings"), dict):
            raise forms.ValidationError("Payload must contain a settings object.")
        return payload["settings"]
