"""Superuser-only, audited user impersonation."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.core.exceptions import ImproperlyConfigured
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from community_base.kernel.decorators import superuser_required
from community_base.studio.audit import hooks
from community_base.studio.route_names import studio_mount_prefix

SESSION_KEY = "_community_base_impersonator_id"

# Prefixes that do not move with the Studio mount: the accounts app, Django admin
# and notifications are fixed apps, not part of the Studio URLconf `route_names`
# walks, so there is nothing to derive them from.
FIXED_SENSITIVE_RETURN_PREFIXES = (
    "/account",
    "/accounts",
    "/admin",
    "/notifications",
)


def _auth_backend():
    """The backend `login()` uses for the impersonation swap and its restore.

    Hardcoding `ModelBackend` broke a site whose `AUTHENTICATION_BACKENDS` does
    not include it: `login()` accepts an unvalidated backend path, so the swap
    appears to succeed, and only the next request discovers the backend cannot
    be loaded -- by which point the operator is anonymous and `stop` cannot
    restore them either, since it logs in through the same broken path.

    A site may configure more than one backend. This picks the first configured
    entry rather than requiring a new setting: `AUTHENTICATION_BACKENDS` is
    already an ordered list by Django's own convention (`authenticate()` tries
    them in that order and treats the first successful one as authoritative),
    every site this package ships to today has zero or one non-default entries
    so the two orderings coincide, and a site that wants a specific backend
    already controls the answer by reordering or trimming its own list -- no
    package setting is needed to express that. A site with an empty list is
    misconfigured for authentication generally, not just for impersonation, so
    this raises loudly rather than guessing.
    """

    backends = list(getattr(settings, "AUTHENTICATION_BACKENDS", ()))
    if not backends:
        raise ImproperlyConfigured(
            "Impersonation needs at least one entry in AUTHENTICATION_BACKENDS."
        )
    return backends[0]


def _sensitive_return_prefixes():
    """Studio's actual mount plus the fixed, non-Studio sensitive prefixes.

    `/studio` used to be a literal here, so a site mounting Studio at `manage/`
    or `backoffice/` kept a guard shaped like it worked while it matched
    nothing: `/manage/users/` and `/backoffice/users/` both passed straight
    through. `studio_mount_prefix()` (`community_base/studio/route_names.py`)
    finds where the site actually mounted `community_base.studio.urls`, so the
    guard covers the same pages regardless of the mount path.
    """

    mount = "/" + studio_mount_prefix().rstrip("/")
    return (mount, *FIXED_SENSITIVE_RETURN_PREFIXES)


def _audit(event, *, actor_ref, target_ref, metadata=None):
    hooks.audit_writer(
        event=event,
        actor_ref=str(actor_ref),
        target_ref=str(target_ref),
        metadata=metadata or {},
    )


def _safe_next(request, default="/"):
    candidate = request.POST.get("next", "")
    if (
        candidate
        and candidate.startswith("/")
        and not candidate.startswith("//")
        and "\\" not in candidate
        and not any(ord(character) < 32 for character in candidate)
        and url_has_allowed_host_and_scheme(
            candidate,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return candidate
    return default


def _safe_public_next(request, default="/"):
    candidate = _safe_next(request, default=default)
    bare_path = candidate.split("?", 1)[0].split("#", 1)[0]
    if any(
        bare_path == prefix or bare_path.startswith(prefix + "/")
        for prefix in _sensitive_return_prefixes()
    ):
        return default
    return candidate


@require_POST
@superuser_required
def start(request, user_id):
    target = get_object_or_404(get_user_model(), pk=user_id)
    actor_id = request.user.pk
    if target.is_superuser:
        _audit("studio.impersonation.refused", actor_ref=actor_id, target_ref=target.pk)
        messages.error(request, "Cannot impersonate a superuser.")
        return redirect(_safe_next(request))

    login(request, target, backend=_auth_backend())
    request.session[SESSION_KEY] = actor_id
    _audit("studio.impersonation.started", actor_ref=actor_id, target_ref=target.pk)
    return redirect(_safe_public_next(request))


@require_POST
def stop(request):
    actor_id = request.session.get(SESSION_KEY)
    if not actor_id:
        return redirect(_safe_public_next(request))

    target_id = getattr(request.user, "pk", "")
    actor = get_user_model().objects.filter(pk=actor_id, is_active=True, is_superuser=True).first()
    if actor is None:
        _audit("studio.impersonation.restore_failed", actor_ref=actor_id, target_ref=target_id)
        logout(request)
        return redirect("/")

    login(request, actor, backend=_auth_backend())
    request.session.pop(SESSION_KEY, None)
    _audit("studio.impersonation.stopped", actor_ref=actor.pk, target_ref=target_id)
    return redirect(_safe_public_next(request))
