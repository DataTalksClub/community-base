from __future__ import annotations

import json

from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from community_base.config import service
from community_base.config.forms import SettingsGroupForm, SettingsImportForm
from community_base.config.registry import groups
from community_base.kernel.decorators import staff_required


def _group_context():
    result = []
    for name, items in groups().items():
        described = []
        for item in items:
            setting = service.describe(item.key)
            value = setting["value"]
            setting["display_value"] = (
                json.dumps(value, indent=2, sort_keys=True)
                if item.value_type in {"json", "list"}
                else value
            )
            described.append(setting)
        result.append({"name": name, "definitions": items, "settings": described})
    return result


@never_cache
@staff_required
def settings_list(request):
    return render(
        request,
        "community_base/config/settings.html",
        {"groups": _group_context(), "import_form": SettingsImportForm()},
    )


@never_cache
@staff_required
def settings_save_group(request, group):
    if request.method != "POST":
        return redirect("community_base_settings")
    group_definitions = groups().get(group)
    if group_definitions is None:
        messages.error(request, "Unknown settings group.")
        return redirect("community_base_settings")
    initial = {item.key: service.get(item.key) for item in group_definitions}
    form = SettingsGroupForm(
        request.POST,
        definitions=group_definitions,
        initial_values=initial,
    )
    if form.is_valid():
        with transaction.atomic():
            for key, value in form.cleaned_updates().items():
                service.set(
                    key,
                    value,
                    actor_ref=f"user:{request.user.pk}",
                    reason=f"Updated Studio group {group}",
                )
        messages.success(request, f"Saved {group} settings.")
    else:
        messages.error(request, f"Could not save {group} settings: {form.errors.as_text()}")
    return redirect("community_base_settings")


@staff_required
def settings_export(request):
    response = JsonResponse({"settings": service.export()})
    response["Content-Disposition"] = 'attachment; filename="community-base-settings.json"'
    return response


@staff_required
def settings_import(request):
    if request.method != "POST":
        return redirect("community_base_settings")
    form = SettingsImportForm(request.POST)
    if form.is_valid():
        try:
            service.import_(
                form.cleaned_data["payload"],
                actor_ref=f"user:{request.user.pk}",
                reason=form.cleaned_data["reason"] or "Imported through Studio",
            )
        except (ImproperlyConfigured, ValidationError) as error:
            messages.error(request, f"Could not import settings: {error}")
        else:
            messages.success(request, "Settings imported.")
    else:
        messages.error(request, f"Could not import settings: {form.errors.as_text()}")
    return redirect("community_base_settings")
