"""Pure prompt rendering for persona catalog value objects.

The public ``render_persona_catalog`` function accepts the ``PersonaInfo``
values used by the onboarding interviewer. This module has no Django, model,
provider or configuration dependency.
"""


def shared_spine_prompts(persona_catalog):
    """Return prompts in every nonempty spine, in the first spine's order."""
    personas = []
    for persona in persona_catalog:
        if persona.questions:
            personas.append(persona)
    if len(personas) < 2:
        return []

    prompt_sets = []
    for persona in personas:
        prompt_sets.append({question.prompt for question in persona.questions})
    shared = set.intersection(*prompt_sets)

    ordered = []
    for question in personas[0].questions:
        if question.prompt in shared and question.prompt not in ordered:
            ordered.append(question.prompt)
    return ordered


def format_question(question):
    """Render one question line, including ordered choice labels when present."""
    options = ""
    if question.options:
        options = f" options: {', '.join(question.options)}"
    return f"  - ({question.question_type}) {question.prompt}{options}"


def _shared_spine_lines(persona_catalog, shared_prompts):
    if not shared_prompts:
        return []
    lines = ["Shared spine -- ask these of EVERY member regardless of archetype:"]
    shared_set = set(shared_prompts)
    rendered = set()
    for persona in persona_catalog:
        for question in persona.questions:
            if question.prompt in shared_set and question.prompt not in rendered:
                lines.append(format_question(question))
                rendered.add(question.prompt)
    lines.append("")
    return lines


def _persona_lines(persona, shared_set, has_shared_spine):
    lines = ["", f"- {persona.archetype} [signal: {persona.signal}]"]
    if persona.description:
        lines.append(f"  {persona.description}")
    deltas = []
    for question in persona.questions:
        if question.prompt not in shared_set:
            deltas.append(question)
    if deltas:
        lines.append("  Delta questions (specific to this archetype):")
        for question in deltas:
            lines.append(format_question(question))
    elif has_shared_spine:
        lines.append("  (no archetype-specific delta questions)")
    return lines


def render_persona_catalog(persona_catalog):
    """Render the shared spine once, followed by each archetype's deltas.

    The input is an ordered sequence of ``PersonaInfo`` values. Empty input
    returns an empty string. The result is the exact catalog suffix appended
    to the onboarding system prompt. Persona names are absent from the input.
    """
    if not persona_catalog:
        return ""
    shared_prompts = shared_spine_prompts(persona_catalog)
    lines = _shared_spine_lines(persona_catalog, shared_prompts)
    lines.append(
        "Archetypes to reason about (internal signal in brackets -- never "
        "say it to the member). Once you commit to one archetype, prioritise "
        "ITS delta questions below and skip the others':"
    )
    shared_set = set(shared_prompts)
    for persona in persona_catalog:
        lines.extend(_persona_lines(persona, shared_set, bool(shared_prompts)))
    return "\n".join(lines)
