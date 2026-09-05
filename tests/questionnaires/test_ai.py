import builtins
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("pydantic", reason="questionnaire AI core requires the ai extra")

from community_base.questionnaires import ai_backend
from community_base.questionnaires.onboarding_ai import (
    GREETING,
    OnboardingExtraction,
    PersonaInfo,
    PersonaQuestion,
    run_onboarding_turn,
)

VALID_EXTRACTION = {
    "persona_signal": "alex",
    "eng_comfort": 4,
    "ai_comfort": 2,
    "primary_goal": "Ship a RAG chatbot",
    "goal_category": "ship_new",
    "time_commitment_hours_per_week": 8,
    "time_profile": "steady",
    "main_blocker": "scoping",
    "secondary_blockers": ["time"],
    "accountability_preference": ["Weekly check-ins"],
    "current_project": "Docs assistant",
    "project_stage": "idea",
    "target_outcome": "A deployed assistant",
    "career_direction": "ai_engineer",
    "tech_stack_known": ["Python"],
    "tech_stack_gaps": ["vector databases"],
    "in_scope": ["retrieval"],
    "out_of_scope": ["fine-tuning"],
    "coding_agent_use": "boilerplate_only",
    "support_wanted": ["Architecture"],
    "learning_track_links": [],
    "hard_deadline": None,
    "plan_horizon": "single_sprint",
    "notes": "",
}
CATALOG = [
    PersonaInfo(
        signal="alex",
        archetype="The Engineer transitioning to AI",
        questions=[
            PersonaQuestion(
                prompt="What would you like to have achieved 6 to 8 weeks from now?",
                question_type="long_text",
            )
        ],
    )
]


def test_disabled_backend_does_not_import_anthropic(settings):
    settings.COMMUNITY_BASE = {**settings.COMMUNITY_BASE, "AI_ONBOARDING": False, "AI_API_KEY": ""}
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "anthropic":
            raise AssertionError("Anthropic imported while disabled")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=guarded_import):
        assert ai_backend.is_enabled() is False


def test_missing_extra_has_actionable_error(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "AI_ONBOARDING": True,
        "AI_API_KEY": "key",
    }
    real_import = builtins.__import__

    def missing_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=missing_import),
        pytest.raises(ai_backend.LLMError, match=r"community-base\[ai\]"),
    ):
        ai_backend.complete([])


def test_provider_response_is_normalized_and_key_is_not_leaked(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "AI_ONBOARDING": True,
        "AI_API_KEY": "secret-key",
    }
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Hello")],
        usage=SimpleNamespace(input_tokens=3, output_tokens=2),
    )
    client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: response), close=lambda: None
    )
    module = SimpleNamespace(Anthropic=lambda **kwargs: client)

    with patch.dict("sys.modules", {"anthropic": module}):
        result = ai_backend.complete([{"role": "user", "content": "Hi"}])

    assert result.text == "Hello"
    assert result.input_tokens == 3


def test_opening_turn_never_calls_provider():
    with patch.object(ai_backend, "complete") as complete:
        result = run_onboarding_turn([], member_message=None, persona_catalog=CATALOG)

    complete.assert_not_called()
    assert result.assistant_message == GREETING
    assert result.is_complete is False


def test_completion_validates_structured_extraction():
    provider_result = ai_backend.LLMResult(
        text="Thanks, that is everything.",
        tool_input=VALID_EXTRACTION,
        tool_name="record_onboarding",
    )
    with patch.object(ai_backend, "complete", return_value=provider_result):
        result = run_onboarding_turn(
            [{"role": "assistant", "content": GREETING}],
            member_message="Done",
            persona_catalog=CATALOG,
        )

    assert result.is_complete is True
    assert isinstance(result.extraction, OnboardingExtraction)
    assert result.extraction.primary_goal == "Ship a RAG chatbot"
    assert result.answers[0].text_value == "Ship a RAG chatbot"


def test_invalid_structured_extraction_is_rejected():
    with (
        patch.object(
            ai_backend,
            "complete",
            return_value=ai_backend.LLMResult(tool_input={"persona_signal": "invalid"}),
        ),
        pytest.raises(ai_backend.LLMError, match="invalid onboarding extraction"),
    ):
        run_onboarding_turn([], member_message="Done", persona_catalog=CATALOG)
