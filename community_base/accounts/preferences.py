def resolve_mail_preference(*, purpose, category, to, user):
    """Apply shared account suppression state to a logical mail delivery."""

    del purpose, to
    if user is None:
        return True
    if getattr(user, "unsubscribed", False):
        return "global_unsubscribed"
    if getattr(user, "bounce_state", "") == "permanent":
        return "permanent_bounce"
    preferences = getattr(user, "email_preferences", {}) or {}
    if category and preferences.get(category) is False:
        return "category_suppressed"
    return True
