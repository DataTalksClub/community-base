import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.questionnaires.models import Persona, Question, Questionnaire, Response
from community_base.questionnaires.services import build_response_questions

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def operator():
    return get_user_model().objects.create_user(email="operator@example.com", is_staff=True)


def test_staff_can_create_questionnaire_and_choice_question(client, operator):
    client.force_login(operator)
    created = client.post(
        reverse("questionnaires_studio_create"),
        {"title": "Welcome", "slug": "welcome", "purpose": "onboarding", "is_active": "on"},
    )
    questionnaire = Questionnaire.objects.get(slug="welcome")
    question_response = client.post(
        reverse("questionnaires_studio_question_create", args=(questionnaire.pk,)),
        {
            "question_type": "single_choice",
            "prompt": "Which path?",
            "order": 0,
            "options": "Engineer\nOther|free_text",
        },
    )

    assert created.status_code == question_response.status_code == 302
    question = Question.objects.get(questionnaire=questionnaire)
    assert list(question.options.values_list("label", "allows_free_text")) == [
        ("Engineer", False),
        ("Other", True),
    ]


def test_question_form_rejects_missing_choice_options(client, operator):
    questionnaire = Questionnaire.objects.create(title="Welcome", purpose="onboarding")
    client.force_login(operator)

    response = client.post(
        reverse("questionnaires_studio_question_create", args=(questionnaire.pk,)),
        {"question_type": "single_choice", "prompt": "Which path?", "order": 0},
    )

    assert response.status_code == 400
    assert b"Choice questions need at least one option" in response.content


def test_persona_requires_onboarding_questionnaire(client, operator):
    feedback = Questionnaire.objects.create(title="Feedback", purpose="feedback")
    client.force_login(operator)

    response = client.post(
        reverse("questionnaires_studio_persona_create"),
        {
            "name": "Engineer",
            "archetype": "Building AI systems",
            "slug": "engineer",
            "default_questionnaire": feedback.pk,
            "is_active": "on",
            "order": 0,
        },
    )

    assert response.status_code == 400
    assert Persona.objects.count() == 0


def test_staff_can_review_response_and_add_custom_question(client, operator):
    member = get_user_model().objects.create_user(email="member@example.com")
    questionnaire = Questionnaire.objects.create(title="Welcome", purpose="onboarding")
    response = Response.objects.create(questionnaire=questionnaire, respondent=member)
    response.mark_submitted()
    build_response_questions(response)
    client.force_login(operator)

    custom = client.post(
        reverse(
            "questionnaires_studio_response_question_create",
            args=(questionnaire.pk, response.pk),
        ),
        {"question_type": "text", "prompt": "Anything else?", "order": 10},
    )
    reviewed = client.post(
        reverse("questionnaires_studio_response_review", args=(questionnaire.pk, response.pk)),
        {"reviewed": "1"},
    )
    response.refresh_from_db()

    assert custom.status_code == reviewed.status_code == 302
    assert response.response_questions.get().is_custom is True
    assert response.review_state == "reviewed"


@pytest.mark.parametrize(
    "route",
    [
        "questionnaires_studio_list",
        "questionnaires_studio_persona_list",
        "questionnaires_studio_response_queue",
    ],
)
def test_nonstaff_is_denied(client, route):
    member = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(member)

    assert client.get(reverse(route)).status_code == 403
