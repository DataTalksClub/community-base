from community_base.kernel.hooks import Hook


def discard_completion(*, attempt_id):
    """Default completion hook when a site has no notification workflow."""


class QuestionnaireAIHooks:
    completed = Hook("AI_ONBOARDING_COMPLETED_HOOK", discard_completion)


hooks = QuestionnaireAIHooks()
