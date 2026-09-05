import pytest
from django.contrib.auth import get_user_model

from community_base.questionnaires.models import (
    Answer,
    AnswerOptionText,
    Persona,
    Question,
    Questionnaire,
    QuestionOption,
    Response,
)
from community_base.questionnaires.onboarding import (
    SELF_ID_MULTIPLE,
    flatten_response_answers,
    has_completed_onboarding,
    reroute_onboarding_response,
    resolve_target_questionnaire,
    self_identification_options,
)
from community_base.questionnaires.services import build_response_questions

pytestmark = pytest.mark.django_db


def add_question(questionnaire, prompt, question_type="long_text", *, option=None, order=0):
    question = Question.objects.create(
        questionnaire=questionnaire,
        prompt=prompt,
        question_type=question_type,
        order=order,
    )
    if option:
        QuestionOption.objects.create(
            question=question,
            label=option,
            allows_free_text=True,
        )
    return question


@pytest.fixture
def onboarding_state():
    generic = Questionnaire.objects.create(
        title="General", slug="onboarding-general", purpose="onboarding"
    )
    focused = Questionnaire.objects.create(title="Engineer", slug="engineer", purpose="onboarding")
    add_question(generic, "Shared goal")
    add_question(generic, "Shared path", "single_choice", option="Other", order=1)
    add_question(generic, "Generic only", order=2)
    add_question(focused, "Shared goal")
    add_question(focused, "Shared path", "single_choice", option="Other", order=1)
    add_question(focused, "Focused only", order=2)
    persona = Persona.objects.create(
        name="Alex",
        archetype="Engineer moving into AI",
        slug="alex",
        default_questionnaire=focused,
    )
    user = get_user_model().objects.create_user(email="member@example.com")
    response = Response.objects.create(questionnaire=generic, respondent=user)
    build_response_questions(response)
    return generic, focused, persona, response


def test_self_identification_never_exposes_internal_persona_name(onboarding_state):
    _generic, focused, persona, _response = onboarding_state

    options = self_identification_options()

    assert options[0]["value"] == str(persona.pk)
    assert options[0]["label"] == "Engineer moving into AI"
    assert "Alex" not in str(options)
    assert resolve_target_questionnaire(str(persona.pk)) == focused
    assert resolve_target_questionnaire(SELF_ID_MULTIPLE).slug == "onboarding-general"


def test_reroute_preserves_shared_answers_and_drops_persona_delta(onboarding_state):
    _generic, focused, _persona, response = onboarding_state
    shared_text = response.response_questions.get(prompt="Shared goal")
    shared_choice = response.response_questions.get(prompt="Shared path")
    generic_only = response.response_questions.get(prompt="Generic only")
    choice = shared_choice.options.get(label="Other")
    Answer.objects.create(response=response, question=shared_text, text_value="Ship a service")
    choice_answer = Answer.objects.create(response=response, question=shared_choice)
    choice_answer.selected_options.add(choice)
    AnswerOptionText.objects.create(
        answer=choice_answer, selected_option=choice, text_value="Pair reviews"
    )
    Answer.objects.create(response=response, question=generic_only, text_value="Drop this")

    reroute_onboarding_response(response, focused)

    response.refresh_from_db()
    assert response.questionnaire == focused
    assert response.answers.get(question__prompt="Shared goal").text_value == "Ship a service"
    restored = response.answers.get(question__prompt="Shared path")
    assert restored.display_value == "Other: Pair reviews"
    assert not response.answers.filter(question__prompt="Generic only").exists()
    assert not response.answers.filter(question__prompt="Focused only").exists()


def test_flatten_response_answers_keeps_unanswered_questions(onboarding_state):
    _generic, _focused, _persona, response = onboarding_state
    question = response.response_questions.get(prompt="Shared goal")
    Answer.objects.create(response=response, question=question, text_value="A result")

    rows = flatten_response_answers(response)

    assert [row["prompt"] for row in rows] == ["Shared goal", "Shared path", "Generic only"]
    assert rows[0]["value"] == "A result"
    assert rows[0]["answered"] is True
    assert rows[1]["value"] is None
    assert rows[1]["answered"] is False


def test_completion_is_derived_from_submitted_response(onboarding_state):
    _generic, _focused, _persona, response = onboarding_state
    assert has_completed_onboarding(response.respondent) is False

    response.mark_submitted()

    assert has_completed_onboarding(response.respondent) is True
