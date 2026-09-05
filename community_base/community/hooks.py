from community_base.kernel.hooks import Hook


def verified_member(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "email_verified", False)
    )


class CommunityHooks:
    eligibility = Hook("COMMUNITY_ELIGIBILITY", verified_member)


hooks = CommunityHooks()
