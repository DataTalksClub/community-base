from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from community_base.questionnaires.models import (
    Answer,
    AnswerOptionText,
    OnboardingConversation,
    OnboardingTurnAttempt,
    Persona,
    Question,
    Questionnaire,
    Response,
    ResponseQuestion,
    ResponseQuestionOption,
)

pytestmark = pytest.mark.django_db(transaction=True)


def make_user(email="member@example.com"):
    return get_user_model().objects.create_user(email=email)


def make_response(*, email="member@example.com", purpose="general"):
    questionnaire = Questionnaire.objects.create(title="Member intake", purpose=purpose)
    return Response.objects.create(questionnaire=questionnaire, respondent=make_user(email))


def test_questionnaire_and_persona_derive_stable_slugs():
    questionnaire = Questionnaire.objects.create(title="Member Intake")
    persona = Persona.objects.create(name="Data Engineer", archetype="Building AI foundations")

    assert questionnaire.slug == "member-intake"
    assert persona.slug == "data-engineer"
    assert persona.display_label == "Data Engineer — Building AI foundations"


def test_response_is_unique_per_questionnaire_and_respondent():
    response = make_response()

    with pytest.raises(IntegrityError), transaction.atomic():
        Response.objects.create(
            questionnaire=response.questionnaire,
            respondent=response.respondent,
        )


def test_submitting_clears_review_state():
    response = make_response()
    reviewer = make_user("reviewer@example.com")
    response.status = "submitted"
    response.reviewed_at = timezone.now()
    response.reviewed_by = reviewer
    response.save()

    response.mark_submitted()

    assert response.status == "submitted"
    assert response.submitted_at is not None
    assert response.review_state == "awaiting"
    assert response.reviewed_at is None
    assert response.reviewed_by is None


def test_draft_cannot_retain_review_state():
    response = make_response()
    response.reviewed_at = timezone.now()

    with pytest.raises(IntegrityError), transaction.atomic():
        response.save()


def test_response_question_exposes_snapshot_identity():
    response = make_response()
    source = Question.objects.create(
        questionnaire=response.questionnaire,
        question_type="text",
        prompt="What are you building?",
    )
    snapshot = ResponseQuestion.objects.create(
        response=response,
        source_question=source,
        question_type=source.question_type,
        prompt=source.prompt,
    )
    custom = ResponseQuestion.objects.create(
        response=response,
        question_type="text",
        prompt="What support do you need?",
    )

    assert snapshot.is_custom is False
    assert custom.is_custom is True


def test_answer_display_value_includes_selected_option_text():
    response = make_response()
    question = ResponseQuestion.objects.create(
        response=response,
        question_type="multiple_choice",
        prompt="Which support helps?",
    )
    option = ResponseQuestionOption.objects.create(
        response_question=question,
        label="Other",
        allows_free_text=True,
    )
    answer = Answer.objects.create(response=response, question=question)
    answer.selected_options.add(option)
    AnswerOptionText.objects.create(
        answer=answer,
        selected_option=option,
        text_value="Architecture review",
    )

    assert answer.display_value == "Other: Architecture review"


def test_only_one_processing_turn_is_allowed_per_conversation():
    response = make_response(purpose="onboarding")
    conversation = OnboardingConversation.objects.create(response=response)
    now = timezone.now()
    defaults = {
        "conversation": conversation,
        "member_message_hash": "a" * 64,
        "admitted_version": 0,
        "transport": "non_stream",
        "started_at": now,
        "lease_expires_at": now + timedelta(minutes=1),
    }
    OnboardingTurnAttempt.objects.create(request_id=uuid4(), **defaults)

    with pytest.raises(IntegrityError), transaction.atomic():
        OnboardingTurnAttempt.objects.create(request_id=uuid4(), **defaults)


def test_turn_attempt_never_stores_member_or_assistant_content():
    field_names = {field.name for field in OnboardingTurnAttempt._meta.get_fields()}

    assert "member_message" not in field_names
    assert "assistant_message" not in field_names
    assert "transcript" not in field_names
