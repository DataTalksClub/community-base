"""Superuser-only, audited user impersonation."""

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from community_base.kernel.decorators import superuser_required
from community_base.studio.audit import hooks

SESSION_KEY = "_community_base_impersonator_id"
AUTH_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _audit(event, *, actor_ref, target_ref, metadata=None):
    hooks.audit_writer(
        event=event,
        actor_ref=str(actor_ref),
        target_ref=str(target_ref),
        metadata=metadata or {},
    )


def _safe_next(request, default="/"):
    candidate = request.POST.get("next", "")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


@require_POST
@superuser_required
def start(request, user_id):
    target = get_object_or_404(get_user_model(), pk=user_id)
    actor_id = request.user.pk
    if target.is_superuser:
        _audit("studio.impersonation.refused", actor_ref=actor_id, target_ref=target.pk)
        messages.error(request, "Cannot impersonate a superuser.")
        return redirect(_safe_next(request))

    login(request, target, backend=AUTH_BACKEND)
    request.session[SESSION_KEY] = actor_id
    _audit("studio.impersonation.started", actor_ref=actor_id, target_ref=target.pk)
    return redirect(_safe_next(request))


@require_POST
def stop(request):
    actor_id = request.session.get(SESSION_KEY)
    if not actor_id:
        return redirect(_safe_next(request))

    target_id = getattr(request.user, "pk", "")
    actor = get_user_model().objects.filter(pk=actor_id, is_active=True, is_superuser=True).first()
    if actor is None:
        _audit("studio.impersonation.restore_failed", actor_ref=actor_id, target_ref=target_id)
        logout(request)
        return redirect("/")

    login(request, actor, backend=AUTH_BACKEND)
    request.session.pop(SESSION_KEY, None)
    _audit("studio.impersonation.stopped", actor_ref=actor.pk, target_ref=target_id)
    return redirect(_safe_next(request))
