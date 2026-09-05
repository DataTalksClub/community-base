from __future__ import annotations

import json

from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from community_base.kernel.decorators import staff_required
from community_base.mail.relay import RelayMailError, configured_client


@never_cache
@staff_required
def template_list(request):
    error = ""
    try:
        templates = configured_client().templates()
    except (RelayMailError, ImproperlyConfigured) as exception:
        templates = ()
        error = exception.code if isinstance(exception, RelayMailError) else "relay_not_configured"
    return render(
        request,
        "community_base/mail/template_list.html",
        {"templates": templates, "error": error},
    )


@never_cache
@staff_required
def template_detail(request, template_key):
    try:
        client = configured_client()
    except ImproperlyConfigured:
        return render(
            request,
            "community_base/mail/template_detail.html",
            {
                "template_key": template_key,
                "versions": (),
                "rendered": None,
                "error": "relay_not_configured",
            },
        )
    rendered = None
    error = ""
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            context = _context(request.POST.get("context", "{}"))
            version = _optional_version(request.POST.get("version", ""))
            if action == "publish":
                client.publish_template(template_key)
                messages.success(request, "Template version published.")
            elif action == "preview":
                rendered = client.preview_template(template_key, context, version=version)
            elif action == "test-send":
                recipient = request.POST.get("recipient", "")
                if not recipient or "@" not in recipient:
                    raise ValueError("invalid recipient")
                client.test_send_template(template_key, recipient, context, version=version)
                messages.success(request, "Test message queued.")
            else:
                raise ValueError("invalid action")
        except (RelayMailError, ValueError, json.JSONDecodeError) as exception:
            error = exception.code if isinstance(exception, RelayMailError) else "invalid_input"
    try:
        versions = client.template_versions(template_key)
    except RelayMailError as exception:
        versions = ()
        error = error or exception.code
    return render(
        request,
        "community_base/mail/template_detail.html",
        {
            "template_key": template_key,
            "versions": versions,
            "rendered": rendered,
            "error": error,
        },
    )


def _context(value: str) -> dict:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("context must be an object")
    return parsed


def _optional_version(value: str) -> int | None:
    if not value:
        return None
    version = int(value)
    if version < 1:
        raise ValueError("invalid version")
    return version
