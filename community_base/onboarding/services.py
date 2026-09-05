from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from community_base.accounts.models import MemberProfile
from community_base.accounts.services.profile import PROFILE_COMPLETION_VERSION
from community_base.onboarding.hooks import hooks
from community_base.onboarding.models import OnboardingProgress, OnboardingStep
from community_base.onboarding.selectors import flow_for
from community_base.onboarding.signals import onboarding_completed
from community_base.questionnaires.models import Response


class OnboardingUnavailable(Exception):
    """No active eligible onboarding flow is available."""


@dataclass(slots=True)
class ProgressState:
    progress: OnboardingProgress
    created: bool


def is_eligible(user):
    return bool(hooks.eligibility(user))


def _first_step(flow):
    return flow.steps.first()


def progress_for(user, *, create=True):
    """Resume an incomplete flow or select and initialize the current flow."""
    if not is_eligible(user):
        raise OnboardingUnavailable("User is not eligible for onboarding")
    existing = (
        OnboardingProgress.objects.filter(user=user, completed_at__isnull=True)
        .select_related("flow", "current_step")
        .order_by("pk")
        .first()
    )
    if existing is not None:
        return ProgressState(existing, False)
    flow = flow_for(user)
    if flow is None:
        raise OnboardingUnavailable("No active onboarding flow is configured")
    if not create:
        existing = (
            OnboardingProgress.objects.filter(user=user, flow=flow)
            .select_related("flow", "current_step")
            .first()
        )
        return ProgressState(existing, False) if existing is not None else None
    progress, created = OnboardingProgress.objects.get_or_create(
        user=user,
        flow=flow,
        defaults={"current_step": _first_step(flow)},
    )
    return ProgressState(progress, created)


def questionnaire_for_step(step):
    slug = str(step.config.get("questionnaire_slug", "")).strip()
    if not slug:
        return None
    from community_base.questionnaires.models import Questionnaire

    return Questionnaire.objects.filter(slug=slug, purpose="onboarding", is_active=True).first()


def response_for_step(progress, step):
    response_id = (progress.data.get("questionnaire_responses") or {}).get(str(step.pk))
    if response_id is None:
        return None
    return Response.objects.filter(pk=response_id, respondent=progress.user).first()


def step_is_complete(progress, step=None):
    step = step or progress.current_step
    if step is None:
        return progress.completed_at is not None
    if str(step.pk) in {str(value) for value in progress.data.get("completed_steps", [])}:
        return True
    if step.kind == OnboardingStep.Kind.PROFILE:
        return MemberProfile.objects.filter(
            user=progress.user, completion_version__gte=PROFILE_COMPLETION_VERSION
        ).exists()
    if step.kind in {OnboardingStep.Kind.QUESTIONNAIRE, OnboardingStep.Kind.AI_CHAT}:
        response = response_for_step(progress, step)
        return response is not None and response.status == "submitted"
    return False


def _record_completed_step(progress, step):
    data = dict(progress.data)
    completed = [str(value) for value in data.get("completed_steps", [])]
    if str(step.pk) not in completed:
        completed.append(str(step.pk))
    data["completed_steps"] = completed
    progress.data = data


def _next_step(step):
    return step.flow.steps.filter(order__gt=step.order).first()


@transaction.atomic
def advance(progress, *, step=None):
    """Mark the current step complete and move atomically to the next one."""
    locked = (
        OnboardingProgress.objects.select_for_update()
        .select_related("flow", "current_step", "user")
        .get(pk=progress.pk)
    )
    current = locked.current_step
    if current is None or locked.completed_at is not None:
        return locked
    if step is not None and current.pk != step.pk:
        return locked
    _record_completed_step(locked, current)
    following = _next_step(current)
    locked.current_step = following
    if following is None:
        locked.completed_at = timezone.now()
    locked.save(update_fields=("current_step", "completed_at", "data"))
    if locked.completed_at is not None:
        transaction.on_commit(
            lambda: onboarding_completed.send(
                sender=OnboardingProgress, user=locked.user, flow=locked.flow
            )
        )
    return locked


def advance_completed(progress):
    """Skip domain steps whose underlying work was already completed."""
    seen = set()
    while progress.current_step_id and progress.current_step_id not in seen:
        seen.add(progress.current_step_id)
        if not step_is_complete(progress):
            break
        progress = advance(progress)
    return progress


def bind_response(progress, step, response):
    data = dict(progress.data)
    responses = dict(data.get("questionnaire_responses") or {})
    responses[str(step.pk)] = response.pk
    data["questionnaire_responses"] = responses
    progress.data = data
    progress.save(update_fields=("data",))
    return progress
