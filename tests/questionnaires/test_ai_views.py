from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytest.importorskip("pydantic", reason="questionnaire AI views require the ai extra")

from community_base.questionnaires.models import Questionnaire
from community_base.questionnaires.onboarding_ai import OnboardingTurnResult
from community_base.questionnaires.services_onboarding_ai import LogicalTurnOutcome

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def member():
    return get_user_model().objects.create_user(email="member@example.com")


@pytest.fixture
def ai_settings(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "AI_ONBOARDING": True,
        "AI_API_KEY": "test-key",
        "AI_ONBOARDING_COMPLETE_URL": "/complete/",
        "AI_ONBOARDING_FALLBACK_URL": "/fallback/",
    }
    Questionnaire.objects.create(
        title="General onboarding", slug="onboarding-general", purpose="onboarding"
    )


def test_disabled_chat_is_not_exposed(client, member, settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "AI_ONBOARDING": False,
        "AI_API_KEY": "",
    }
    client.force_login(member)

    assert client.get(reverse("questionnaires_ai_chat")).status_code == 404


def test_chat_is_member_owned_and_seeds_greeting(client, member, ai_settings):
    client.force_login(member)

    response = client.get(reverse("questionnaires_ai_chat"))

    assert response.status_code == 200
    assert b"Tell us what you want to build" in response.content
    assert b"To start:" in response.content
    assert response.context["response"].respondent == member


def test_message_requires_request_identity(client, member, ai_settings):
    client.force_login(member)

    response = client.post(reverse("questionnaires_ai_message"), {"message": "Hello"})

    assert response.status_code == 400
    assert b"Please retry" in response.content


def test_message_persists_only_through_logical_turn_service(client, member, ai_settings):
    client.force_login(member)
    request_id = uuid4()
    result = LogicalTurnOutcome(
        result=OnboardingTurnResult(assistant_message="What outcome matters?"),
        attempt_id=42,
    )
    with patch(
        "community_base.questionnaires.services_onboarding_ai.run_logical_member_turn",
        return_value=result,
    ) as run:
        response = client.post(
            reverse("questionnaires_ai_message"),
            {"message": "I want to ship", "request_id": str(request_id)},
        )

    assert response.status_code == 200
    assert run.call_args.args[1:] == (str(request_id), "I want to ship")


def test_completed_member_cannot_restart_chat(client, member, ai_settings):
    questionnaire = Questionnaire.objects.get(slug="onboarding-general")
    response = questionnaire.responses.create(respondent=member)
    response.mark_submitted()
    client.force_login(member)

    result = client.get(reverse("questionnaires_ai_chat"))

    assert result.status_code == 302
    assert result.url == "/complete/"


def test_stream_sets_sse_no_buffer_headers(client, member, ai_settings):
    client.force_login(member)
    with patch(
        "community_base.questionnaires.services_onboarding_ai.stream_logical_member_turn",
        return_value=iter(
            (
                "Hello",
                LogicalTurnOutcome(
                    result=OnboardingTurnResult(assistant_message="Hello"), attempt_id=1
                ),
            )
        ),
    ):
        response = client.post(
            reverse("questionnaires_ai_stream"),
            {"message": "Hi", "request_id": str(uuid4())},
        )
        content = b"".join(response.streaming_content)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Cache-Control"] == "no-cache"
    assert response["X-Accel-Buffering"] == "no"
    assert b"event: delta" in content
    assert b"event: done" in content
