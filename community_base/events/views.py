from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from community_base.events.anonymous_registration import (
    cancel_anonymous_registration,
    confirm_anonymous_registration,
    request_anonymous_registration,
)
from community_base.events.feedback import submit_feedback
from community_base.events.forms import AnonymousEventRegistrationForm, EventFeedbackForm
from community_base.events.integrations.calendar import generate_ics
from community_base.events.models import Event, EventAlias, EventRegistration
from community_base.events.registration import register_for_event, unregister_from_event
from community_base.events.routing import event_url
from community_base.events.services import can_register_for_event
from community_base.events.tokens import RegistrationTokenError

PUBLIC_STATUSES = ("upcoming", "completed")


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _lookup_event(*, slug, public_id=None):
    events = Event.objects.filter(status__in=PUBLIC_STATUSES).select_related("event_series")
    if public_id is not None:
        return get_object_or_404(events, public_id=public_id)
    event = events.filter(slug=slug).order_by("-start_datetime", "-pk").first()
    if event is None:
        raise Http404
    return event


def _event_and_redirect(*, slug, public_id=None):
    event = _lookup_event(slug=slug, public_id=public_id)
    canonical = event_url(event)
    if slug != event.slug or canonical.rstrip("/") != _request_path(public_id, slug):
        return event, redirect(canonical, permanent=True)
    return event, None


def _request_path(public_id, slug):
    if public_id is None:
        return f"/events/{slug}"
    return f"/events/{public_id}/{slug}"


def _registration_for_user(event, user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return EventRegistration.objects.filter(event=event, user=user).first()


@require_GET
def event_list(request):
    events = Event.objects.filter(status__in=PUBLIC_STATUSES).prefetch_related(
        "event_host_links__host"
    )
    upcoming = [event for event in events if event.is_upcoming]
    past = [event for event in events if event.is_past]
    return render(
        request,
        "events/event_list.html",
        {"upcoming_events": upcoming, "past_events": past, "event_url": event_url},
    )


@require_GET
def event_detail(request, slug, public_id=None):
    event, canonical_redirect = _event_and_redirect(slug=slug, public_id=public_id)
    if canonical_redirect is not None:
        return canonical_redirect
    registration = _registration_for_user(event, request.user)
    feedback = getattr(registration, "feedback", None) if registration else None
    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "registration": registration,
            "can_register": can_register_for_event(request.user, event),
            "anonymous_form": AnonymousEventRegistrationForm(),
            "feedback": feedback,
            "feedback_form": EventFeedbackForm(
                initial={
                    "rating": getattr(feedback, "rating", None),
                    "comment": getattr(feedback, "comment", ""),
                    "would_change": getattr(feedback, "would_change", ""),
                }
            ),
        },
    )


@require_POST
def event_register(request, slug, public_id=None):
    event = _lookup_event(slug=slug, public_id=public_id)
    if request.user.is_authenticated:
        try:
            _registration, changed = register_for_event(event, request.user)
        except (PermissionDenied, ValidationError) as error:
            messages.error(request, str(error))
        else:
            messages.success(
                request, "You are registered." if changed else "You are registered already."
            )
        return redirect(event_url(event))

    form = AnonymousEventRegistrationForm(request.POST)
    if form.is_valid():
        try:
            result = request_anonymous_registration(
                event,
                form.cleaned_data["email"],
                display_name=form.cleaned_data["display_name"],
                privacy_notice_version="web-1",
                newsletter_consent=form.cleaned_data["newsletter_consent"],
                newsletter_consent_version="web-1",
                newsletter_consent_source="event-registration",
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            message = (
                "Check your email to confirm your registration."
                if result.delivery is not None
                else "This email is registered already."
            )
            return _private(
                render(
                    request,
                    "events/registration_result.html",
                    {"event": event, "success": True, "message": message},
                )
            )
    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "registration": None,
            "can_register": event.required_level == 0 and event.is_upcoming,
            "anonymous_form": form,
            "feedback": None,
            "feedback_form": EventFeedbackForm(),
        },
        status=400,
    )


@require_POST
def event_unregister(request, slug, public_id=None):
    if not request.user.is_authenticated:
        raise PermissionDenied
    event = _lookup_event(slug=slug, public_id=public_id)
    try:
        _registration, changed = unregister_from_event(event, request.user)
    except ValidationError as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request, "Registration cancelled." if changed else "No active registration found."
        )
    return redirect(event_url(event))


@require_GET
def registration_verify(request):
    try:
        registration, changed = confirm_anonymous_registration(request.GET.get("token", ""))
    except RegistrationTokenError as error:
        message = (
            "This verification link has expired."
            if error.code == "expired"
            else "This verification link is invalid."
        )
        return _private(
            render(
                request,
                "events/registration_result.html",
                {"success": False, "message": message},
                status=400,
            )
        )
    return _private(
        render(
            request,
            "events/registration_result.html",
            {
                "event": registration.event,
                "success": True,
                "message": (
                    "Your registration is confirmed."
                    if changed
                    else "Your registration was confirmed already."
                ),
            },
        )
    )


@require_http_methods(("GET", "POST"))
def registration_manage(request):
    token = request.GET.get("token") or request.POST.get("token", "")
    if request.method == "POST":
        try:
            registration, changed = cancel_anonymous_registration(token)
        except RegistrationTokenError:
            return _private(
                render(
                    request,
                    "events/registration_result.html",
                    {"success": False, "message": "This management link is invalid or expired."},
                    status=400,
                )
            )
        return _private(
            render(
                request,
                "events/registration_result.html",
                {
                    "event": registration.event,
                    "success": True,
                    "message": (
                        "Your registration is cancelled."
                        if changed
                        else "Your registration was cancelled already."
                    ),
                },
            )
        )
    return _private(render(request, "events/registration_manage.html", {"token": token}))


@require_POST
def event_feedback(request, slug, public_id=None):
    if not request.user.is_authenticated:
        raise PermissionDenied
    event = _lookup_event(slug=slug, public_id=public_id)
    registration = get_object_or_404(EventRegistration, event=event, user=request.user)
    form = EventFeedbackForm(request.POST)
    if form.is_valid():
        try:
            submit_feedback(registration, user=request.user, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Feedback saved.")
            return redirect(event_url(event))
    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "registration": registration,
            "can_register": False,
            "anonymous_form": AnonymousEventRegistrationForm(),
            "feedback": getattr(registration, "feedback", None),
            "feedback_form": form,
        },
        status=400,
    )


@require_GET
def event_calendar(request, slug, public_id=None):
    event = _lookup_event(slug=slug, public_id=public_id)
    attendee_email = request.user.email if request.user.is_authenticated else None
    response = HttpResponse(
        generate_ics(event, audience="attendee", attendee_email=attendee_email),
        content_type="text/calendar; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{event.slug}.ics"'
    return response


@require_GET
def event_alias(request, alias):
    path = request.path.rstrip("/")
    event_alias = get_object_or_404(
        EventAlias.objects.select_related("event"),
        source_path=path,
        event__status__in=PUBLIC_STATUSES,
    )
    return redirect(event_url(event_alias.event), permanent=True)
