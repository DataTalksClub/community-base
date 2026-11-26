"""Staff-triggered project results email for exact attempt submitters.

Modeled on CMP's completed-project score notification flow, using
``community_base.mail.send()`` and ``COURSEWORK_PROJECT_RESULTS_URL_BUILDER``:

- Preview is read-only and reports the exact eligible recipient count.
- Closing reviews alone (moving a project to ``Completed``) never sends mail,
  and existing completed attempts are never replayed automatically.
- Explicit send is gated on ``ProjectState.COMPLETED`` for dated attempts,
  deduplicates unique submitters independent of pass/fail, excludes
  non-submitters, volunteer-only rows, and other attempts, and never includes
  grades or other recipients in the email context.
- A unique per-attempt ``ProjectResultsNotification`` record protects against
  double-clicks and concurrent sends, while ``ProjectResultsNotificationRecipient``
  links each learner to their audited ``EmailDelivery`` row and supports
  idempotent retry of ``dead`` deliveries via ``community_base.mail.resend()``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from community_base.coursework.hooks import hooks
from community_base.coursework.models import (
    ProjectResultsNotification,
    ProjectResultsNotificationRecipient,
    ProjectState,
)
from community_base.coursework.notifications import PROJECT_RESULTS_PURPOSE
from community_base.kernel.redaction import redact
from community_base.mail.models import EmailDelivery
from community_base.mail.service import resend, send
from community_base.mail.studio import masked_email

logger = logging.getLogger(__name__)


class ProjectResultsNotificationError(ValueError):
    """Raised when a project results notification action is not allowed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class EligibleRecipient:
    user: object
    email: str
    submission: object


@dataclass(frozen=True)
class EligibleAudience:
    recipients: tuple[EligibleRecipient, ...]
    total_submissions: int
    excluded_duplicate_count: int
    excluded_no_email_count: int

    @property
    def eligible_count(self) -> int:
        return len(self.recipients)


@dataclass(frozen=True)
class RecipientDeliveryRow:
    recipient_id: int
    delivery_id: str
    masked_email: str
    state: str
    state_label: str
    reason_code: str
    job_status: str
    job_attempts: int
    job_max_attempts: int
    last_error: str
    retry_count: int
    can_retry: bool


@dataclass(frozen=True)
class ProjectResultsNotificationStatus:
    notification_id: int
    course_slug: str
    cohort_slug: str
    project_slug: str
    eligible_count: int
    enqueued_count: int
    suppressed_count: int
    total_recipients: int
    pending_count: int
    accepted_or_delivered_count: int
    retryable_count: int
    dead_count: int
    ambiguous_count: int
    bounced_or_complained_count: int
    created_at: object
    triggered_by_label: str
    recipients: tuple[RecipientDeliveryRow, ...]

    @property
    def has_retryable_failures(self) -> bool:
        return self.dead_count > 0


@dataclass(frozen=True)
class ProjectResultsPreview:
    course_slug: str
    course_title: str
    cohort_slug: str
    project_slug: str
    project_title: str
    eligible_count: int
    total_submissions: int
    excluded_duplicate_count: int
    excluded_no_email_count: int
    can_send: bool
    already_sent: bool
    blocked_code: str
    blocked_reason: str
    results_url_sample: str | None
    status: ProjectResultsNotificationStatus | None


@dataclass(frozen=True)
class ProjectResultsSendResult:
    created: bool
    already_sent: bool
    notification: ProjectResultsNotification
    status: ProjectResultsNotificationStatus


@dataclass(frozen=True)
class ProjectResultsRetryResult:
    retried_count: int
    status: ProjectResultsNotificationStatus


def _is_self_paced(project) -> bool:
    if hasattr(project, "uses_pooled_review"):
        return bool(project.uses_pooled_review)
    return bool(getattr(project, "is_self_paced", False))


def _project_scope(project) -> tuple[str, str, str, str, str, str]:
    """Return ``(course_slug, course_title, cohort_slug, project_slug, scope_key, scope_hash)``."""
    if getattr(project, "course", None) is not None:
        course = project.course
        cohort = getattr(project, "cohort", None)
        cohort_slug = ""
        if cohort is not None:
            cohort_slug = (
                getattr(cohort, "slug", None)
                or getattr(cohort, "external_key", None)
                or f"cohort-{cohort.pk}"
            )
    else:
        cohort = project.cohort
        course = cohort.course
        cohort_slug = cohort.slug
    project_slug = project.slug
    scope_key = f"{course.slug}:{cohort_slug}:{project_slug}"
    scope_hash = hashlib.sha256(scope_key.encode()).hexdigest()
    return course.slug, course.title, cohort_slug, project_slug, scope_key, scope_hash


def _project_state_gate(project) -> tuple[bool, str, str]:
    if _is_self_paced(project):
        return (
            False,
            "self_paced_not_supported",
            "Self-paced attempts do not support project-wide results mailing.",
        )
    if project.state != ProjectState.COMPLETED.value:
        return (
            False,
            "project_not_completed",
            "Project must be in Completed state before sending results emails.",
        )
    return True, "", ""


def _submission_user(submission):
    return getattr(submission, "student", None) or getattr(submission, "user", None)


def _eligible_audience(project) -> EligibleAudience:
    qs = project.submissions.all()
    model = qs.model
    if hasattr(model, "student"):
        qs = qs.select_related("student")
    elif hasattr(model, "user"):
        qs = qs.select_related("user")
    if hasattr(model, "volunteer_review_only"):
        qs = qs.filter(volunteer_review_only=False)
    if getattr(project, "course_id", None) and hasattr(model, "course_id"):
        qs = qs.filter(course_id=project.course_id)
    if getattr(project, "cohort_id", None) and hasattr(model, "cohort_id"):
        qs = qs.filter(cohort_id=project.cohort_id)
    qs = qs.order_by("submitted_at", "pk")

    recipients: list[EligibleRecipient] = []
    seen_user_ids: set[int] = set()
    total_submissions = 0
    excluded_duplicate_count = 0
    excluded_no_email_count = 0

    for submission in qs:
        total_submissions += 1
        user = _submission_user(submission)
        user_id = getattr(user, "pk", None)
        if user is None or user_id is None:
            excluded_no_email_count += 1
            continue
        if user_id in seen_user_ids:
            excluded_duplicate_count += 1
            continue
        email = (getattr(user, "email", "") or "").strip()
        if not email or "@" not in email:
            excluded_no_email_count += 1
            continue
        seen_user_ids.add(user_id)
        recipients.append(EligibleRecipient(user=user, email=email, submission=submission))

    return EligibleAudience(
        recipients=tuple(recipients),
        total_submissions=total_submissions,
        excluded_duplicate_count=excluded_duplicate_count,
        excluded_no_email_count=excluded_no_email_count,
    )


def _recipient_idempotency_key(scope_key: str, user_id: int) -> str:
    raw = f"{PROJECT_RESULTS_PURPOSE}:{scope_key}:u{user_id}"
    if len(raw) <= 200:
        return raw
    digest = hashlib.sha256(scope_key.encode()).hexdigest()[:24]
    return f"{PROJECT_RESULTS_PURPOSE}:{digest}:u{user_id}"


def _build_status(notification: ProjectResultsNotification) -> ProjectResultsNotificationStatus:
    rows: list[RecipientDeliveryRow] = []
    pending_count = 0
    accepted_or_delivered_count = 0
    suppressed_count = 0
    retryable_count = 0
    dead_count = 0
    ambiguous_count = 0
    bounced_or_complained_count = 0

    recipients = notification.recipients.select_related("delivery", "delivery__job").order_by("id")
    for item in recipients:
        delivery = item.delivery
        state = delivery.state
        if state in (
            EmailDelivery.State.PENDING,
            EmailDelivery.State.QUEUED,
            EmailDelivery.State.LEASED,
        ):
            pending_count += 1
        elif state in (
            EmailDelivery.State.PROVIDER_ACCEPTED,
            EmailDelivery.State.DELIVERED,
        ):
            accepted_or_delivered_count += 1
        elif state == EmailDelivery.State.SUPPRESSED:
            suppressed_count += 1
        elif state == EmailDelivery.State.RETRYABLE:
            retryable_count += 1
        elif state == EmailDelivery.State.DEAD:
            dead_count += 1
        elif state == EmailDelivery.State.AMBIGUOUS:
            ambiguous_count += 1
        elif state in (
            EmailDelivery.State.HARD_BOUNCED,
            EmailDelivery.State.COMPLAINED,
        ):
            bounced_or_complained_count += 1

        job = delivery.job
        rows.append(
            RecipientDeliveryRow(
                recipient_id=item.pk,
                delivery_id=str(delivery.pk),
                masked_email=masked_email(delivery.recipient_email),
                state=state,
                state_label=delivery.get_state_display(),
                reason_code=delivery.reason_code,
                job_status=job.status if job is not None else "",
                job_attempts=job.attempts if job is not None else 0,
                job_max_attempts=job.max_attempts if job is not None else 0,
                last_error=redact(job.last_error) if job is not None and job.last_error else "",
                retry_count=item.retry_count,
                can_retry=state == EmailDelivery.State.DEAD,
            )
        )

    actor_label = notification.triggered_by_label

    return ProjectResultsNotificationStatus(
        notification_id=notification.pk,
        course_slug=notification.course_slug,
        cohort_slug=notification.cohort_slug,
        project_slug=notification.project_slug,
        eligible_count=notification.eligible_count,
        enqueued_count=notification.enqueued_count,
        suppressed_count=suppressed_count,
        total_recipients=len(rows),
        pending_count=pending_count,
        accepted_or_delivered_count=accepted_or_delivered_count,
        retryable_count=retryable_count,
        dead_count=dead_count,
        ambiguous_count=ambiguous_count,
        bounced_or_complained_count=bounced_or_complained_count,
        created_at=notification.created_at,
        triggered_by_label=actor_label,
        recipients=tuple(rows),
    )


def get_project_results_notification_status(
    project,
) -> ProjectResultsNotificationStatus | None:
    """Return auditable job and per-recipient delivery state for ``project``, or ``None``."""
    _course_slug, _course_title, _cohort_slug, _project_slug, _scope_key, scope_hash = (
        _project_scope(project)
    )
    notification = ProjectResultsNotification.objects.filter(scope_hash=scope_hash).first()
    if notification is None:
        return None
    return _build_status(notification)


def preview_project_results_notifications(project) -> ProjectResultsPreview:
    """Read-only preview of exact eligible recipients and gate status for one project attempt."""
    course_slug, course_title, cohort_slug, project_slug, _scope_key, scope_hash = _project_scope(
        project
    )
    allowed, blocked_code, blocked_reason = _project_state_gate(project)
    audience = _eligible_audience(project)
    existing = ProjectResultsNotification.objects.filter(scope_hash=scope_hash).first()
    status = _build_status(existing) if existing is not None else None
    already_sent = existing is not None
    if already_sent and not blocked_code:
        blocked_code = "already_sent"
        blocked_reason = "Results emails have already been triggered for this project attempt."
    elif allowed and audience.eligible_count == 0:
        blocked_code = "no_eligible_recipients"
        blocked_reason = "No eligible submitters with an email address were found."

    sample_recipient = audience.recipients[0] if audience.recipients else None
    results_url_sample = hooks.project_results_url_builder(
        project=project,
        submission=sample_recipient.submission if sample_recipient else None,
        user=sample_recipient.user if sample_recipient else None,
    )
    can_send = allowed and not already_sent and audience.eligible_count > 0

    return ProjectResultsPreview(
        course_slug=course_slug,
        course_title=course_title,
        cohort_slug=cohort_slug,
        project_slug=project_slug,
        project_title=project.title,
        eligible_count=audience.eligible_count,
        total_submissions=audience.total_submissions,
        excluded_duplicate_count=audience.excluded_duplicate_count,
        excluded_no_email_count=audience.excluded_no_email_count,
        can_send=can_send,
        already_sent=already_sent,
        blocked_code=blocked_code,
        blocked_reason=blocked_reason,
        results_url_sample=results_url_sample,
        status=status,
    )


def send_project_results_notifications(
    project,
    *,
    actor=None,
) -> ProjectResultsSendResult:
    """Queue one ``coursework.project_results`` email per unique eligible submitter.

    Concurrency-safe and idempotent per ``(course, cohort, project)`` attempt: a second or
    concurrent call returns ``created=False, already_sent=True`` without queueing duplicate mail.
    """
    allowed, blocked_code, blocked_reason = _project_state_gate(project)
    if not allowed:
        raise ProjectResultsNotificationError(blocked_code, blocked_reason)

    course_slug, course_title, cohort_slug, project_slug, scope_key, scope_hash = _project_scope(
        project
    )
    meta = getattr(project, "_meta", None)
    related_type = meta.label_lower if meta is not None else ""
    related_id = str(getattr(project, "pk", "") or "")
    actor_user = actor if getattr(actor, "pk", None) else None
    actor_ref = str(actor_user.pk) if actor_user is not None else ""
    actor_label = masked_email(getattr(actor_user, "email", "") or "") if actor_user else ""

    with transaction.atomic():
        existing = (
            ProjectResultsNotification.objects.select_for_update()
            .filter(scope_hash=scope_hash)
            .first()
        )
        if existing is not None:
            return ProjectResultsSendResult(
                created=False,
                already_sent=True,
                notification=existing,
                status=_build_status(existing),
            )

        audience = _eligible_audience(project)
        if audience.eligible_count == 0:
            raise ProjectResultsNotificationError(
                "no_eligible_recipients",
                "No eligible submitters with an email address were found for this attempt.",
            )

        try:
            with transaction.atomic():
                notification = ProjectResultsNotification.objects.create(
                    scope_hash=scope_hash,
                    course_slug=course_slug,
                    cohort_slug=cohort_slug,
                    project_slug=project_slug,
                    project_title=project.title,
                    related_object_type=related_type,
                    related_object_id=related_id,
                    triggered_by_ref=actor_ref,
                    triggered_by_label=actor_label,
                    eligible_count=audience.eligible_count,
                )
        except IntegrityError:
            existing = ProjectResultsNotification.objects.get(scope_hash=scope_hash)
            return ProjectResultsSendResult(
                created=False,
                already_sent=True,
                notification=existing,
                status=_build_status(existing),
            )

        enqueued_count = 0
        suppressed_count = 0
        for recipient in audience.recipients:
            results_url = hooks.project_results_url_builder(
                project=project,
                submission=recipient.submission,
                user=recipient.user,
            )
            context = {
                "course_slug": course_slug,
                "course_title": course_title,
                "cohort_slug": cohort_slug,
                "project_slug": project_slug,
                "project_title": project.title,
            }
            if results_url:
                context["results_url"] = results_url
                context["project_results_url"] = results_url
            delivery = send(
                PROJECT_RESULTS_PURPOSE,
                recipient.email,
                context,
                _recipient_idempotency_key(scope_key, recipient.user.pk),
                category="coursework",
                user=recipient.user,
                related=recipient.submission,
            )
            if delivery.state == EmailDelivery.State.SUPPRESSED:
                suppressed_count += 1
            else:
                enqueued_count += 1
            ProjectResultsNotificationRecipient.objects.create(
                notification=notification,
                recipient_user_id=str(recipient.user.pk),
                submission_id=str(recipient.submission.pk),
                delivery=delivery,
            )

        notification.enqueued_count = enqueued_count
        notification.suppressed_count = suppressed_count
        notification.save(update_fields=["enqueued_count", "suppressed_count", "updated_at"])

        logger.info(
            "Project results notifications queued: scope=%s eligible=%d "
            "enqueued=%d suppressed=%d by=%s",
            scope_key,
            audience.eligible_count,
            enqueued_count,
            suppressed_count,
            redact(getattr(actor_user, "email", None) or "system"),
        )
        return ProjectResultsSendResult(
            created=True,
            already_sent=False,
            notification=notification,
            status=_build_status(notification),
        )


def retry_failed_project_results_notifications(
    project,
    *,
    actor=None,
) -> ProjectResultsRetryResult:
    """Retry only terminal ``dead`` deliveries via ``community_base.mail.resend()``."""
    _course_slug, _course_title, _cohort_slug, _project_slug, scope_key, scope_hash = (
        _project_scope(project)
    )
    with transaction.atomic():
        notification = (
            ProjectResultsNotification.objects.select_for_update()
            .filter(scope_hash=scope_hash)
            .first()
        )
        if notification is None:
            raise ProjectResultsNotificationError(
                "notification_not_found",
                "No results notification job exists for this project attempt yet.",
            )
        recipients = list(
            notification.recipients.select_for_update().select_related("delivery").order_by("id")
        )
        retried_count = 0
        for item in recipients:
            if item.delivery.state != EmailDelivery.State.DEAD:
                continue
            replacement = resend(item.delivery)
            item.delivery = replacement
            item.retry_count += 1
            item.save(update_fields=["delivery", "retry_count", "updated_at"])
            retried_count += 1

        logger.info(
            "Project results notifications retried: scope=%s retried=%d by=%s",
            scope_key,
            retried_count,
            redact(getattr(actor, "email", None) or "system"),
        )
        return ProjectResultsRetryResult(
            retried_count=retried_count,
            status=_build_status(notification),
        )
