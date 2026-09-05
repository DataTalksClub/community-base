import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.questionnaires.models import (
    Persona,
    Question,
    Questionnaire,
    QuestionOption,
    Response,
    ResponseQuestion,
)
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


@pytest.mark.parametrize(
    ("route_name", "build_rows"),
    [
        (
            "questionnaires_studio_question_reorder",
            lambda questionnaire: [
                Question.objects.create(
                    questionnaire=questionnaire, question_type="text", prompt=prompt, order=index
                )
                for index, prompt in enumerate(("First", "Second"))
            ],
        ),
        (
            "questionnaires_studio_persona_reorder",
            lambda questionnaire: [
                Persona.objects.create(
                    name=name, archetype="Builder", slug=name.lower(), order=index
                )
                for index, name in enumerate(("First", "Second"))
            ],
        ),
    ],
)
def test_staff_can_reorder_questionnaire_collections(client, operator, route_name, build_rows):
    questionnaire = Questionnaire.objects.create(title="Welcome", purpose="onboarding")
    rows = build_rows(questionnaire)
    args = (questionnaire.pk,) if "question_" in route_name else ()
    client.force_login(operator)

    result = client.post(
        reverse(route_name, args=args),
        data=json.dumps([{"id": rows[0].pk, "order": 9}, {"id": rows[1].pk, "order": 2}]),
        content_type="application/json",
    )

    assert result.status_code == 200
    rows[0].refresh_from_db()
    rows[1].refresh_from_db()
    assert (rows[0].order, rows[1].order) == (9, 2)


def test_option_reorder_rejects_cross_question_ids_without_writes(client, operator):
    questionnaire = Questionnaire.objects.create(title="Welcome", purpose="onboarding")
    question = Question.objects.create(
        questionnaire=questionnaire, question_type="single_choice", prompt="Path?"
    )
    other_question = Question.objects.create(
        questionnaire=questionnaire, question_type="single_choice", prompt="Other?"
    )
    option = QuestionOption.objects.create(question=question, label="One", order=0)
    foreign_option = QuestionOption.objects.create(question=other_question, label="Two", order=1)
    client.force_login(operator)

    result = client.post(
        reverse("questionnaires_studio_option_reorder", args=(questionnaire.pk, question.pk)),
        data=json.dumps([{"id": option.pk, "order": 8}, {"id": foreign_option.pk, "order": 9}]),
        content_type="application/json",
    )

    assert result.status_code == 400
    option.refresh_from_db()
    assert option.order == 0


def test_reorder_does_not_change_response_snapshots(client, operator):
    member = get_user_model().objects.create_user(email="snapshot@example.com")
    questionnaire = Questionnaire.objects.create(title="Welcome", purpose="onboarding")
    question = Question.objects.create(
        questionnaire=questionnaire, question_type="text", prompt="Original", order=0
    )
    response = Response.objects.create(questionnaire=questionnaire, respondent=member)
    build_response_questions(response)
    snapshot = ResponseQuestion.objects.get(response=response)
    before = (snapshot.prompt, snapshot.order, snapshot.source_question_id)
    client.force_login(operator)

    result = client.post(
        reverse("questionnaires_studio_question_reorder", args=(questionnaire.pk,)),
        data=json.dumps([{"id": question.pk, "order": 7}]),
        content_type="application/json",
    )

    assert result.status_code == 200
    snapshot.refresh_from_db()
    assert (snapshot.prompt, snapshot.order, snapshot.source_question_id) == before


def test_questionnaire_response_list_is_scoped(client, operator):
    member = get_user_model().objects.create_user(email="member@example.com")
    first = Questionnaire.objects.create(title="First")
    second = Questionnaire.objects.create(title="Second")
    visible = Response.objects.create(questionnaire=first, respondent=member)
    Response.objects.create(questionnaire=second, respondent=member)
    client.force_login(operator)

    result = client.get(reverse("questionnaires_studio_responses", args=(first.pk,)))

    assert result.status_code == 200
    assert list(result.context["responses"].object_list) == [visible]
