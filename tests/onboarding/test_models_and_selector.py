import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from community_base.onboarding.models import (
    FlowAssignment,
    OnboardingFlow,
    OnboardingProgress,
    OnboardingStep,
)
from community_base.onboarding.selectors import flow_for

pytestmark = pytest.mark.django_db(transaction=True)


def test_flow_for_prefers_highest_priority_matching_group():
    default = OnboardingFlow.objects.create(slug="default", title="Default", is_default=True)
    lower = OnboardingFlow.objects.create(slug="lower", title="Lower")
    higher = OnboardingFlow.objects.create(slug="higher", title="Higher")
    group = Group.objects.create(name="learners")
    user = get_user_model().objects.create_user(email="member@example.com")
    user.groups.add(group)
    FlowAssignment.objects.create(flow=lower, group=group, priority=10)
    FlowAssignment.objects.create(flow=higher, group=group, priority=20)

    assert flow_for(user) == higher
    user.groups.clear()
    assert flow_for(user) == default


def test_flow_for_matches_configured_access_level(settings):
    class LevelPolicy:
        def can_access(self, user, required_level):
            return user.level >= required_level

        def user_level(self, user):
            return user.level

        def level_label(self, level):
            return str(level)

    settings.COMMUNITY_BASE = {"ACCESS_POLICY": LevelPolicy()}
    default = OnboardingFlow.objects.create(slug="default", title="Default", is_default=True)
    paid = OnboardingFlow.objects.create(slug="paid", title="Paid")
    FlowAssignment.objects.create(flow=paid, min_level=10, priority=50)
    user = get_user_model().objects.create_user(email="paid@example.com")
    user.level = 10

    assert flow_for(user) == paid
    user.level = 5
    assert flow_for(user) == default


def test_only_one_default_flow_is_allowed():
    OnboardingFlow.objects.create(slug="first", title="First", is_default=True)
    with pytest.raises(IntegrityError):
        OnboardingFlow.objects.create(slug="second", title="Second", is_default=True)


def test_progress_rejects_step_from_another_flow():
    user = get_user_model().objects.create_user(email="member@example.com")
    first = OnboardingFlow.objects.create(slug="first", title="First")
    second = OnboardingFlow.objects.create(slug="second", title="Second")
    wrong_step = OnboardingStep.objects.create(flow=second, order=1, kind="profile")
    progress = OnboardingProgress(user=user, flow=first, current_step=wrong_step)

    with pytest.raises(ValidationError, match="Current step must belong to the flow"):
        progress.full_clean()


def test_assignment_requires_a_group_or_level():
    flow = OnboardingFlow.objects.create(slug="default", title="Default")

    with pytest.raises(ValidationError, match="Choose a group or minimum access level"):
        FlowAssignment(flow=flow).full_clean()


@pytest.mark.parametrize(
    ("kind", "config", "message"),
    [
        ("questionnaire", {}, "questionnaire_slug or persona_selection"),
        ("custom", {}, "Custom steps need a template"),
    ],
)
def test_steps_validate_kind_specific_configuration(kind, config, message):
    flow = OnboardingFlow.objects.create(slug="default", title="Default")

    with pytest.raises(ValidationError, match=message):
        OnboardingStep(flow=flow, order=0, kind=kind, config=config).full_clean()


def test_flow_cannot_mix_questionnaire_and_ai_chat_steps():
    flow = OnboardingFlow.objects.create(slug="default", title="Default")
    OnboardingStep.objects.create(
        flow=flow,
        order=0,
        kind="questionnaire",
        config={"questionnaire_slug": "welcome"},
    )

    with pytest.raises(ValidationError, match="either a questionnaire or AI chat"):
        OnboardingStep(flow=flow, order=1, kind="ai_chat").full_clean()
