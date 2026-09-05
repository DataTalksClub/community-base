import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from community_base.onboarding.models import FlowAssignment, OnboardingFlow, OnboardingStep

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def operator():
    return get_user_model().objects.create_user(email="operator@example.com", is_staff=True)


def test_staff_can_author_flow_step_and_assignment(client, operator):
    group = Group.objects.create(name="learners")
    client.force_login(operator)
    created = client.post(
        reverse("onboarding_studio_flow_create"),
        {"slug": "learners", "title": "Learners", "active": "on"},
    )
    flow = OnboardingFlow.objects.get(slug="learners")
    step_result = client.post(
        reverse("onboarding_studio_step_create", args=(flow.pk,)),
        {"order": 0, "kind": "custom", "config": '{"template": "base.html"}', "required": "on"},
    )
    assignment_result = client.post(
        reverse("onboarding_studio_assignment_create", args=(flow.pk,)),
        {"group": group.pk, "min_level": "", "priority": 20},
    )

    assert created.status_code == step_result.status_code == assignment_result.status_code == 302
    assert OnboardingStep.objects.get(flow=flow).config == {"template": "base.html"}
    assert FlowAssignment.objects.get(flow=flow).group == group


@pytest.mark.parametrize(
    "route",
    ("onboarding_studio_flow_list", "onboarding_studio_progress_list"),
)
def test_studio_pages_reject_nonstaff(client, route):
    user = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(user)

    assert client.get(reverse(route)).status_code == 403
