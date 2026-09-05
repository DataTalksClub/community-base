from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from community_base.api.forms import APIKeyCreateForm
from community_base.api.models import APIKey
from community_base.kernel.decorators import superuser_required


@never_cache
@superuser_required
def api_keys(request):
    plaintext = None
    created_key = None
    if request.method == "POST":
        form = APIKeyCreateForm(request.POST)
        if form.is_valid():
            created_key, plaintext = APIKey.create_for_user(
                user=form.cleaned_data["user"],
                name=form.cleaned_data["name"],
                scopes=form.cleaned_data["scopes"],
                kind=form.cleaned_data["kind"],
            )
            form = APIKeyCreateForm()
    else:
        form = APIKeyCreateForm()
    return render(
        request,
        "community_base/api/api_keys.html",
        {
            "api_keys": APIKey.objects.select_related("user"),
            "created_key": created_key,
            "form": form,
            "plaintext": plaintext,
        },
    )


@superuser_required
def revoke_api_key(request, key_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    api_key = get_object_or_404(APIKey, pk=key_id)
    if request.POST.get("confirmation") != "revoke":
        messages.error(request, "Type revoke to confirm API key revocation.")
        return redirect("community_base_api_keys")
    api_key.revoke()
    messages.success(request, "API key revoked.")
    return redirect("community_base_api_keys")
