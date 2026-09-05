from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

pytest.importorskip("pydantic", reason="questionnaire AI persistence requires the ai extra")

from community_base.questionnaires.models import (
    Answer,
    OnboardingTurnAttempt,
    Persona,
    Question,
    Questionnaire,
)
from community_base.questionnaires.onboarding_ai import (
    ExtractedAnswer,
    OnboardingExtraction,
    OnboardingTurnResult,
)
from community_base.questionnaires.services_onboarding_ai import (
    TurnRequestError,
    get_or_create_ai_onboarding_response,
    run_logical_member_turn,
)
from tests.questionnaires.test_ai import VALID_EXTRACTION

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def conversation():
    questionnaire = Questionnaire.objects.create(
        title="General onboarding", slug="onboarding-general", purpose="onboarding"
    )
    Question.objects.create(
        questionnaire=questionnaire,
        question_type="long_text",
        prompt="What would you like to have achieved 6 to 8 weeks from now?",
        is_required=True,
    )
    user = get_user_model().objects.create_user(email="member@example.com")
    response, result = get_or_create_ai_onboarding_response(user)
    return result


def test_get_or_create_reuses_one_response_and_conversation(conversation):
    response = conversation.response

    reused_response, reused_conversation = get_or_create_ai_onboarding_response(response.respondent)

    assert reused_response == response
    assert reused_conversation == conversation
    assert response.response_questions.count() == 1


def test_logical_turn_is_deduplicated_and_contains_no_content_telemetry(conversation):
    request_id = uuid4()
    result = OnboardingTurnResult(assistant_message="What tends to block you?")
    with patch(
        "community_base.questionnaires.services_onboarding_ai.run_onboarding_turn",
        return_value=result,
    ):
        outcome = run_logical_member_turn(conversation, request_id, "I want to ship")
        replay = run_logical_member_turn(conversation, request_id, "I want to ship")

    conversation.refresh_from_db()
    attempt = OnboardingTurnAttempt.objects.get(pk=outcome.attempt_id)
    assert replay.replayed is True
    assert conversation.transcript == [
        {"role": "user", "content": "I want to ship"},
        {"role": "assistant", "content": "What tends to block you?"},
    ]
    assert attempt.status == "succeeded"
    assert attempt.outcome == "intermediate"
    assert attempt.member_message_hash != "I want to ship"
    assert "I want to ship" not in str(attempt.__dict__)


def test_reusing_request_id_with_changed_content_is_rejected(conversation):
    request_id = uuid4()
    result = OnboardingTurnResult(assistant_message="Next question")
    with patch(
        "community_base.questionnaires.services_onboarding_ai.run_onboarding_turn",
        return_value=result,
    ):
        run_logical_member_turn(conversation, request_id, "Original")
        with pytest.raises(TurnRequestError, match="altered_message"):
            run_logical_member_turn(conversation, request_id, "Changed")


def test_completed_turn_routes_persona_writes_answers_and_calls_hook(conversation, settings):
    generic = conversation.response.questionnaire
    persona_questionnaire = Questionnaire.objects.create(
        title="Engineer onboarding", slug="engineer-onboarding", purpose="onboarding"
    )
    prompt = "What would you like to have achieved 6 to 8 weeks from now?"
    Question.objects.create(
        questionnaire=persona_questionnaire,
        question_type="long_text",
        prompt=prompt,
    )
    Persona.objects.create(
        name="Alex",
        archetype="The Engineer transitioning to AI",
        slug="alex",
        default_questionnaire=persona_questionnaire,
    )
    events = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "AI_ONBOARDING_COMPLETED_HOOK": lambda **event: events.append(event),
    }
    extraction = OnboardingExtraction.model_validate(VALID_EXTRACTION)
    result = OnboardingTurnResult(
        assistant_message="Thanks, that is everything.",
        is_complete=True,
        extraction=extraction,
        answers=[
            ExtractedAnswer(
                prompt=prompt,
                question_type="long_text",
                text_value=extraction.primary_goal,
            )
        ],
    )
    with patch(
        "community_base.questionnaires.services_onboarding_ai.run_onboarding_turn",
        return_value=result,
    ):
        outcome = run_logical_member_turn(conversation, uuid4(), "Final answer")

    response = conversation.response
    response.refresh_from_db()
    conversation.refresh_from_db()
    assert response.questionnaire == persona_questionnaire
    assert response.status == "submitted"
    assert conversation.persona_signal == "alex"
    assert Answer.objects.get(response=response).text_value == extraction.primary_goal
    assert OnboardingTurnAttempt.objects.get(pk=outcome.attempt_id).outcome == "final"
    assert events == [{"attempt_id": outcome.attempt_id}]
    assert generic != response.questionnaire
