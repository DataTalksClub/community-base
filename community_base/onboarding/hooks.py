from community_base.kernel.hooks import Hook


def authenticated_eligibility(user):
    return bool(getattr(user, "is_authenticated", False))


def unavailable_plan_step(*, request, step, progress):
    return {"available": False}


class OnboardingHooks:
    eligibility = Hook("ONBOARDING_ELIGIBILITY", authenticated_eligibility)
    plan_step = Hook("ONBOARDING_PLAN_STEP", unavailable_plan_step)


hooks = OnboardingHooks()
