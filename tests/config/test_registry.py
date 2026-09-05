import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError

from community_base.config.registry import declare, definition, groups


def test_declare_preserves_all_metadata():
    declared = declare(
        key="TEST_REGISTRY_EMAIL",
        group="testing",
        label="Test email",
        description="Recipient used in tests.",
        value_type="str",
        default="",
        secret=True,
        multiline=True,
        optional=True,
        is_email=True,
        django_settings_fallback="TEST_EMAIL_SETTING",
        env_var="TEST_EMAIL_ENV",
        docs_url="docs/testing.md#email",
    )

    assert definition(declared.key) == declared
    assert declared in groups()["testing"]
    assert declared.secret and declared.multiline and declared.optional and declared.is_email


def test_conflicting_declaration_is_rejected():
    declare(
        key="TEST_REGISTRY_CONFLICT",
        group="testing",
        label="Original",
        description="Original declaration.",
        value_type="str",
        default="",
    )

    with pytest.raises(ImproperlyConfigured, match="Conflicting"):
        declare(
            key="TEST_REGISTRY_CONFLICT",
            group="testing",
            label="Changed",
            description="Changed declaration.",
            value_type="str",
            default="",
        )


@pytest.mark.parametrize(
    ("value_type", "raw", "expected"),
    [
        ("str", 12, "12"),
        ("int", "12", 12),
        ("bool", "yes", True),
        ("json", '{"enabled": true}', {"enabled": True}),
        ("list", '["one", "two"]', ["one", "two"]),
    ],
)
def test_supported_value_types(value_type, raw, expected):
    declared = declare(
        key=f"TEST_TYPE_{value_type.upper()}",
        group="testing",
        label=value_type,
        description="Type conversion test.",
        value_type=value_type,
        default=expected,
    )

    assert declared.coerce(raw) == expected


def test_email_metadata_validates_values():
    declared = declare(
        key="TEST_REGISTRY_INVALID_EMAIL",
        group="testing",
        label="Email",
        description="Email validation test.",
        value_type="str",
        default="",
        optional=True,
        is_email=True,
    )

    with pytest.raises(ValidationError):
        declared.coerce("not-an-email")
