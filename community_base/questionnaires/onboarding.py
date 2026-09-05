from community_base.kernel import conf
from community_base.questionnaires.models import Persona, Questionnaire, Response

GENERIC_ONBOARDING_SLUG = "onboarding-general"
SELF_ID_NONE = "none"
SELF_ID_MULTIPLE = "multiple"


def _clamped_int(name, default, minimum, maximum):
    try:
        value = int(conf.get(name))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def onboarding_ai_deadline_seconds():
    return _clamped_int("AI_ONBOARDING_DEADLINE_SECONDS", 25, 5, 28)


def onboarding_ai_max_attempts():
    return _clamped_int("AI_ONBOARDING_MAX_ATTEMPTS", 2, 1, 3)


def get_onboarding_response(user):
    return (
        Response.objects.filter(respondent=user, questionnaire__purpose="onboarding")
        .select_related("questionnaire")
        .order_by("created_at")
        .first()
    )


def get_generic_onboarding_questionnaire():
    return Questionnaire.objects.filter(slug=GENERIC_ONBOARDING_SLUG, purpose="onboarding").first()


def has_completed_onboarding(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and Response.objects.filter(
            respondent=user, questionnaire__purpose="onboarding", status="submitted"
        ).exists()
    )


def self_identification_options():
    options = [
        {"value": str(item.pk), "label": item.archetype, "help_text": item.description}
        for item in Persona.objects.filter(
            is_active=True, default_questionnaire__isnull=False
        ).order_by("order", "name")
    ]
    options.extend(
        (
            {"value": SELF_ID_NONE, "label": "None of these / not sure", "help_text": ""},
            {"value": SELF_ID_MULTIPLE, "label": "More than one / both", "help_text": ""},
        )
    )
    return options


def resolve_target_questionnaire(selection):
    generic = get_generic_onboarding_questionnaire()
    if selection in {SELF_ID_NONE, SELF_ID_MULTIPLE}:
        return generic
    if selection and selection.isdigit():
        persona = (
            Persona.objects.filter(pk=int(selection), is_active=True)
            .select_related("default_questionnaire")
            .first()
        )
        if persona is not None and persona.default_questionnaire is not None:
            return persona.default_questionnaire
    return generic
