import pytest

from community_base.studio.user_registry import (
    register_user_badge,
    register_user_column,
    register_user_panel,
    user_badges,
    user_columns,
    user_panels,
)


def test_user_extension_registries_preserve_registration_order():
    first = lambda user: "first"  # noqa: E731
    second = lambda user: "second"  # noqa: E731
    register_user_column("first", "First", first)
    register_user_column("second", "Second", second)
    register_user_badge(first)
    register_user_panel("Panel", "panel.html", second)

    assert [column.key for column in user_columns()] == ["first", "second"]
    assert user_badges() == (first,)
    assert user_panels()[0].context_provider is second


def test_duplicate_extension_keys_are_rejected():
    register_user_column("same", "Same", str)
    with pytest.raises(ValueError, match="already registered"):
        register_user_column("same", "Again", repr)
