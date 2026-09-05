from django.db import transaction
from django.db.models import Case, Count, DateTimeField, F, IntegerField, Q, When
from django.utils import timezone

from community_base.questionnaires.models import Response
from community_base.studio.audit import hooks as studio_hooks

VALID_RESPONSE_STATUSES = ("submitted", "draft", "all")
VALID_REVIEW_FILTERS = ("awaiting", "reviewed", "all")
VALID_PURPOSES = ("onboarding", "feedback", "general", "all")


class ResponseNotSubmitted(Exception):
    """Raised when an operator tries to review a draft response."""


def response_queryset(*, include_answers=False):
    queryset = Response.objects.select_related("questionnaire", "respondent", "reviewed_by")
    if include_answers:
        queryset = queryset.prefetch_related(
            "response_questions__options",
            "answers__selected_options",
            "answers__option_texts",
        )
    return queryset


def filter_response_queryset(
    queryset,
    *,
    status="submitted",
    review="awaiting",
    purpose="all",
    questionnaire=None,
    search="",
):
    if status not in VALID_RESPONSE_STATUSES:
        raise ValueError("Invalid response status filter")
    if review not in VALID_REVIEW_FILTERS:
        raise ValueError("Invalid review filter")
    if purpose not in VALID_PURPOSES:
        raise ValueError("Invalid questionnaire purpose filter")
    if status != "all":
        queryset = queryset.filter(status=status)
    if review != "all":
        if status == "draft":
            return queryset.none()
        queryset = queryset.filter(status="submitted", reviewed_at__isnull=review == "awaiting")
    if purpose != "all":
        queryset = queryset.filter(questionnaire__purpose=purpose)
    if questionnaire is not None:
        queryset = queryset.filter(questionnaire_id=questionnaire)
    if search:
        queryset = queryset.filter(
            Q(respondent__email__icontains=search)
            | Q(respondent__first_name__icontains=search)
            | Q(respondent__last_name__icontains=search)
            | Q(questionnaire__title__icontains=search)
            | Q(questionnaire__slug__icontains=search)
        )
    return queryset.annotate(
        response_sort_group=Case(
            When(status="submitted", then=0), default=1, output_field=IntegerField()
        ),
        response_sort_at=Case(
            When(status="submitted", then=F("submitted_at")),
            default=F("updated_at"),
            output_field=DateTimeField(),
        ),
    ).order_by(
        "response_sort_group",
        F("response_sort_at").desc(nulls_last=True),
        "-pk",
    )


def compact_response_queryset(**filters):
    return filter_response_queryset(
        response_queryset().annotate(answered_count=Count("answers", distinct=True)), **filters
    )


def transition_response_review(*, response_id, reviewed, actor, questionnaire_id=None):
    """Review or reopen a submitted response with row locking and portable audit."""
    with transaction.atomic():
        queryset = Response.objects.select_related(
            "questionnaire", "respondent"
        ).select_for_update()
        if questionnaire_id is not None:
            queryset = queryset.filter(questionnaire_id=questionnaire_id)
        response = queryset.get(pk=response_id)
        if response.status != "submitted":
            raise ResponseNotSubmitted
        previous_state = response.review_state
        changed = False
        if reviewed and response.reviewed_at is None:
            response.reviewed_at = timezone.now()
            response.reviewed_by = actor
            changed = True
        elif not reviewed and response.reviewed_at is not None:
            response.reviewed_at = None
            response.reviewed_by = None
            changed = True
        if changed:
            response.save(update_fields=("reviewed_at", "reviewed_by", "updated_at"))
            studio_hooks.audit_writer(
                event=(
                    "questionnaires.response.reviewed"
                    if reviewed
                    else "questionnaires.response.reopened"
                ),
                actor_ref=str(actor.pk),
                subject_ref=str(response.pk),
                questionnaire_ref=str(response.questionnaire_id),
                previous_state=previous_state,
                new_state=response.review_state,
            )
    return response, changed
