"""Exact prompt bytes for the existing pure persona catalog renderer."""

import pytest

from community_base.questionnaires.onboarding_ai import (
    PersonaInfo,
    PersonaQuestion,
    _render_persona_catalog,
)
from community_base.questionnaires.onboarding_ai import (
    __all__ as onboarding_exports,
)
from community_base.questionnaires.onboarding_ai import (
    render_persona_catalog as onboarding_render_persona_catalog,
)
from community_base.questionnaires.persona_catalog import render_persona_catalog


def question(prompt, question_type="long_text", options=None):
    return PersonaQuestion(
        prompt=prompt,
        question_type=question_type,
        options=options or [],
    )


def test_empty_catalog_renders_empty_string():
    assert "render_persona_catalog" in onboarding_exports
    assert _render_persona_catalog is render_persona_catalog
    assert onboarding_render_persona_catalog is render_persona_catalog
    assert _render_persona_catalog([]) == ""
    assert _render_persona_catalog(None) == ""


def test_single_persona_keeps_all_questions_as_deltas():
    catalog = [
        PersonaInfo(
            signal="engineer",
            archetype="The engineer",
            description="Builds practical systems.",
            questions=[
                question("Goal?"),
                question("Choose", "single_choice", ["First", "Second"]),
            ],
        )
    ]

    assert _render_persona_catalog(catalog) == (
        "Archetypes to reason about (internal signal in brackets -- never "
        "say it to the member). Once you commit to one archetype, prioritise "
        "ITS delta questions below and skip the others':\n"
        "\n"
        "- The engineer [signal: engineer]\n"
        "  Builds practical systems.\n"
        "  Delta questions (specific to this archetype):\n"
        "  - (long_text) Goal?\n"
        "  - (single_choice) Choose options: First, Second"
    )


def two_persona_catalog():
    return [
        PersonaInfo(
            signal="one",
            archetype="First",
            questions=[
                question("Shared?", "single_choice", ["A", "B"]),
                question("Only first?"),
                question("Shared?", "single_choice", ["A", "B"]),
            ],
        ),
        PersonaInfo(
            signal="two",
            archetype="Second",
            questions=[
                question("Only second?", "number"),
                question("Shared?", "single_choice", ["Different"]),
            ],
        ),
    ]


def test_shared_spine_uses_first_personas_choices_and_keeps_delta_order():
    catalog = two_persona_catalog()

    assert _render_persona_catalog(catalog) == (
        "Shared spine -- ask these of EVERY member regardless of archetype:\n"
        "  - (single_choice) Shared? options: A, B\n"
        "\n"
        "Archetypes to reason about (internal signal in brackets -- never "
        "say it to the member). Once you commit to one archetype, prioritise "
        "ITS delta questions below and skip the others':\n"
        "\n"
        "- First [signal: one]\n"
        "  Delta questions (specific to this archetype):\n"
        "  - (long_text) Only first?\n"
        "\n"
        "- Second [signal: two]\n"
        "  Delta questions (specific to this archetype):\n"
        "  - (number) Only second?"
    )


def test_shared_only_persona_has_explicit_no_delta_line():
    catalog = [
        PersonaInfo(signal="one", archetype="First", questions=[question("Shared?")]),
        PersonaInfo(signal="two", archetype="Second", questions=[question("Shared?")]),
    ]

    assert _render_persona_catalog(catalog) == (
        "Shared spine -- ask these of EVERY member regardless of archetype:\n"
        "  - (long_text) Shared?\n"
        "\n"
        "Archetypes to reason about (internal signal in brackets -- never "
        "say it to the member). Once you commit to one archetype, prioritise "
        "ITS delta questions below and skip the others':\n"
        "\n"
        "- First [signal: one]\n"
        "  (no archetype-specific delta questions)\n"
        "\n"
        "- Second [signal: two]\n"
        "  (no archetype-specific delta questions)"
    )


def test_invalid_catalog_item_keeps_attribute_error():
    with pytest.raises(AttributeError, match="questions"):
        _render_persona_catalog([{"signal": "raw"}])
