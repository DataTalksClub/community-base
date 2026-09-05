from community_base.config.registry import declare

declare(
    key="TEST_FEATURE_ENABLED",
    group="testproject",
    label="Test feature enabled",
    description="Fixture flag proving installed apps can declare runtime settings.",
    value_type="bool",
    default=False,
    optional=True,
)
