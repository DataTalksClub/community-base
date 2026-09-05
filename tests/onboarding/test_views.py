import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from community_base.onboarding.models import (
    FlowAssignment,
    OnboardingFlow,
    OnboardingProgress,
    OnboardingStep,
)
from community_base.questionnaires.models import Question, Questionnaire, Response
from community_base.questionnaires.services import build_response_questions, field_name

pytestmark = pytest.mark.django_db(transaction=True)


def member(email="member@example.com"):
    return get_user_model().objects.create_user(email=email, email_verified=True)


def flow_with_step(kind, *, config=None, required=True, slug="default", default=True):
    flow = OnboardingFlow.objects.create(slug=slug, title=slug.title(), is_default=default)
    step = OnboardingStep.objects.create(
        flow=flow, order=0, kind=kind, config=config or {}, required=required
    )
    return flow, step


def test_testproject_selects_group_flow_and_default_flow(client):
    default, _default_step = flow_with_step("custom", config={"template": "base.html"})
    learners, _learner_step = flow_with_step(
        "custom", config={"template": "base.html"}, slug="learners", default=False
    )
    group = Group.objects.create(name="learners")
    FlowAssignment.objects.create(flow=learners, group=group, priority=10)
    grouped = member("grouped@example.com")
    grouped.groups.add(group)
    ordinary = member("ordinary@example.com")

    client.force_login(grouped)
    assert client.get(reverse("community_base_onboarding_start")).status_code == 302
    assert OnboardingProgress.objects.get(user=grouped).flow == learners
    client.force_login(ordinary)
    assert client.get(reverse("community_base_onboarding_start")).status_code == 302
    assert OnboardingProgress.objects.get(user=ordinary).flow == default


def test_profile_step_updates_profile_and_completes_flow(client):
    user = member()
    flow, _step = flow_with_step("profile")
    client.force_login(user)
    client.get(reverse("community_base_onboarding_start"))

    result = client.post(
        reverse("community_base_onboarding_submit"),
        {
            "country": "DE",
            "work_status": "employed",
            "organisation": "Example",
            "professional_role": "software_engineer_backend",
            "seniority": "senior",
            "about": "I build systems.",
            "ambitions": "Ship an ML service.",
            "why_joined": "Learn with peers.",
            "github_url": "",
            "linkedin_url": "",
            "website_url": "",
        },
    )

    assert result.status_code == 302
    assert OnboardingProgress.objects.get(user=user, flow=flow).completed_at is not None


def test_questionnaire_step_saves_and_submits_snapshot_answers(client):
    user = member()
    questionnaire = Questionnaire.objects.create(
        title="Welcome", slug="welcome", purpose="onboarding"
    )
    question = Question.objects.create(
        questionnaire=questionnaire,
        question_type="text",
        prompt="What are you building?",
        is_required=True,
    )
    flow, _step = flow_with_step("questionnaire", config={"questionnaire_slug": questionnaire.slug})
    client.force_login(user)
    client.get(reverse("community_base_onboarding_start"))
    page = client.get(reverse("community_base_onboarding_step"))
    response = Response.objects.get(respondent=user, questionnaire=questionnaire)
    snapshot = response.response_questions.get(source_question=question)

    result = client.post(
        reverse("community_base_onboarding_submit"), {field_name(snapshot): "A service"}
    )

    assert page.status_code == 200
    assert result.status_code == 302
    response.refresh_from_db()
    assert response.status == "submitted"
    assert OnboardingProgress.objects.get(user=user, flow=flow).completed_at is not None


def test_ai_step_consumes_existing_submitted_onboarding_response(client):
    user = member()
    questionnaire = Questionnaire.objects.create(
        title="AI", slug="onboarding-general", purpose="onboarding"
    )
    response = Response.objects.create(
        questionnaire=questionnaire, respondent=user, status="submitted"
    )
    build_response_questions(response)
    flow, _step = flow_with_step("ai_chat")
    client.force_login(user)

    client.get(reverse("community_base_onboarding_start"))
    result = client.get(reverse("community_base_onboarding_step"))

    assert result.status_code == 302
    assert result.url == reverse("community_base_onboarding_start")
    assert OnboardingProgress.objects.get(user=user, flow=flow).completed_at is not None


def test_plan_hook_and_optional_custom_step_can_advance(client, settings):
    user = member()
    flow = OnboardingFlow.objects.create(slug="default", title="Default", is_default=True)
    plan = OnboardingStep.objects.create(flow=flow, order=0, kind="plan")
    custom = OnboardingStep.objects.create(
        flow=flow,
        order=1,
        kind="custom",
        config={"template": "base.html"},
        required=False,
    )
    settings.COMMUNITY_BASE = {
        "ONBOARDING_PLAN_STEP": lambda **values: {
            "available": True,
            "complete": values["request"].method == "POST",
        }
    }
    client.force_login(user)
    client.get(reverse("community_base_onboarding_start"))

    plan_result = client.post(reverse("community_base_onboarding_submit"))
    skip_result = client.post(reverse("community_base_onboarding_submit"), {"action": "skip"})

    assert plan_result.status_code == skip_result.status_code == 302
    progress = OnboardingProgress.objects.get(user=user, flow=flow)
    assert progress.completed_at is not None
    assert str(plan.pk) in progress.data["completed_steps"]
    assert str(custom.pk) in progress.data["completed_steps"]


def test_ineligible_member_gets_forbidden_and_no_progress(client, settings):
    settings.COMMUNITY_BASE = {"ONBOARDING_ELIGIBILITY": lambda user: False}
    user = member()
    flow_with_step("profile")
    client.force_login(user)

    result = client.get(reverse("community_base_onboarding_start"))

    assert result.status_code == 403
    assert not OnboardingProgress.objects.filter(user=user).exists()


def test_dashboard_prompt_is_hidden_when_no_flow_is_available(client):
    user = member()
    client.force_login(user)

    result = client.get(reverse("community_base_onboarding_prompt"))

    assert result.status_code == 200
    assert result.content == b""
