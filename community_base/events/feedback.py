from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from community_base.events.models import EventFeedback, EventRegistration


@transaction.atomic
def submit_feedback(
    registration,
    *,
    user,
    rating=None,
    comment="",
    would_change="",
):
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Authentication is required to submit feedback.")
    registration = (
        EventRegistration.objects.select_for_update()
        .select_related("event", "user")
        .get(pk=registration.pk)
    )
    if registration.user_id != user.pk:
        raise PermissionDenied("Feedback belongs to the registration owner.")
    if registration.status not in {
        EventRegistration.Status.CONFIRMED,
        EventRegistration.Status.ATTENDED,
    }:
        raise ValidationError("An active registration is required for feedback.")
    if timezone.now() < registration.event.effective_end_datetime:
        raise ValidationError("Feedback opens after the event ends.")
    feedback, created = EventFeedback.objects.get_or_create(registration=registration)
    feedback.rating = rating
    feedback.comment = str(comment).strip()
    feedback.would_change = str(would_change).strip()
    feedback.full_clean()
    feedback.save()
    return feedback, created
