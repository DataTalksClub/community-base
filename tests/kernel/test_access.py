from types import SimpleNamespace

from community_base.kernel.access import (
    LEVEL_BASIC,
    LEVEL_OPEN,
    LEVEL_REGISTERED,
    can_access,
    level_label,
)


def test_open_policy_access_levels():
    anonymous = SimpleNamespace(is_authenticated=False)
    authenticated = SimpleNamespace(is_authenticated=True)

    assert can_access(None, LEVEL_OPEN)
    assert not can_access(anonymous, LEVEL_REGISTERED)
    assert can_access(authenticated, LEVEL_REGISTERED)
    assert not can_access(authenticated, LEVEL_BASIC)


def test_access_accepts_object_and_labels_unknown_levels():
    content = SimpleNamespace(required_level=LEVEL_OPEN)

    assert can_access(None, content)
    assert level_label(LEVEL_REGISTERED) == "Registered"
    assert level_label(17) == "17"
