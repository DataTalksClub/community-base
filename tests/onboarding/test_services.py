import pytest
from django.contrib.auth import get_user_model

from community_base.accounts.models import MemberProfile
from community_base.onboarding.models import OnboardingFlow, OnboardingStep
from community_base.onboarding.services import (
    OnboardingUnavailable,
    advance,
    advance_completed,
    bind_response,
    progress_for,
)
from community_base.onboarding.signals import onboarding_completed
from community_base.questionnaires.models import Questionnaire, Response

pytestmark = pytest.mark.django_db(transaction=True)


def build_flow(*kinds):
    flow = OnboardingFlow.objects.create(slug="default", title="Default", is_default=True)
    return flow, [
        OnboardingStep.objects.create(flow=flow, order=index, kind=kind)
        for index, kind in enumerate(kinds)
    ]


def test_progress_starts_at_first_step_and_resumes_it():
    user = get_user_model().objects.create_user(email="member@example.com")
    _flow, steps = build_flow("profile", "custom")

    first = progress_for(user)
    resumed = progress_for(user)

    assert first.created is True
    assert resumed.created is False
    assert resumed.progress.pk == first.progress.pk
    assert resumed.progress.current_step == steps[0]


def test_ineligible_user_gets_no_progress(settings):
    settings.COMMUNITY_BASE = {"ONBOARDING_ELIGIBILITY": lambda user: False}
    user = get_user_model().objects.create_user(email="member@example.com")
    build_flow("profile")

    with pytest.raises(OnboardingUnavailable):
        progress_for(user)


def test_completed_profile_is_skipped_and_completion_signal_is_emitted():
    user = get_user_model().objects.create_user(email="member@example.com")
    flow, _steps = build_flow("profile")
    MemberProfile.objects.create(user=user, completion_version=1)
    events = []

    def receiver(sender, **kwargs):
        events.append(kwargs)

    onboarding_completed.connect(receiver)
    try:
        progress = advance_completed(progress_for(user).progress)
    finally:
        onboarding_completed.disconnect(receiver)

    assert progress.completed_at is not None
    assert events[0]["user"] == user
    assert events[0]["flow"] == flow


def test_bound_submitted_questionnaire_response_is_skipped():
    user = get_user_model().objects.create_user(email="member@example.com")
    _flow, (step,) = build_flow("questionnaire")
    questionnaire = Questionnaire.objects.create(title="Welcome", purpose="onboarding")
    response = Response.objects.create(
        questionnaire=questionnaire, respondent=user, status="submitted"
    )
    progress = progress_for(user).progress
    bind_response(progress, step, response)

    assert advance_completed(progress).completed_at is not None


def test_advance_rejects_a_stale_step_without_moving_progress():
    user = get_user_model().objects.create_user(email="member@example.com")
    _flow, steps = build_flow("custom", "plan")
    progress = progress_for(user).progress
    progress = advance(progress, step=steps[0])

    stale_result = advance(progress, step=steps[0])

    assert stale_result.current_step == steps[1]


def test_empty_flow_completes_without_a_missing_step_failure():
    user = get_user_model().objects.create_user(email="member@example.com")
    flow = OnboardingFlow.objects.create(slug="default", title="Default", is_default=True)

    progress = advance_completed(progress_for(user).progress)

    assert progress.flow == flow
    assert progress.current_step is None
    assert progress.completed_at is not None


def test_deleted_current_step_resumes_at_first_unfinished_step():
    user = get_user_model().objects.create_user(email="member@example.com")
    _flow, steps = build_flow("custom", "plan")
    progress = progress_for(user).progress
    steps[0].delete()

    repaired = advance_completed(progress)

    assert repaired.current_step == steps[1]
