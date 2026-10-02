from community_base.config.registry import declare_if_absent

declare_if_absent(
    key="COURSEWORK_AUTOMATION_ENABLED",
    group="coursework",
    label="Coursework automation enabled",
    description=(
        "Allow pooled batch formation and scoring, review expiry, and coursework reminders."
    ),
    value_type="bool",
    default=True,
    django_settings_fallback=True,
    docs_url="community_base/coursework/README.md#automation-guard",
)
