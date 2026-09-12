from types import SimpleNamespace

import pytest

from community_base.studio.registry import (
    Destination,
    DestinationGroup,
    Section,
    active_state,
    register,
    sections,
)


def destination(key="items", routes=("studio_item_list", "studio_item_detail"), order=10):
    return Destination(
        key=key,
        title=key.title(),
        url_name="studio_dashboard",
        route_names=routes,
        order=order,
    )


def test_sections_are_sorted_with_their_destinations():
    register(
        Section(
            "later",
            "Later",
            20,
            "clock",
            (destination("z", routes=("studio_later",), order=20),),
        )
    )
    register(
        Section(
            "earlier",
            "Earlier",
            10,
            "sun",
            (destination("a", routes=("studio_earlier",), order=10),),
        )
    )

    assert [section.slug for section in sections()] == [
        "home",
        "earlier",
        "later",
        "people",
        "operations",
    ]
    assert sections()[1].destinations[0].key == "a"


def test_matching_section_metadata_merges_app_destinations():
    register(Section("shared", "Shared", 10, "box", (destination("first", ("first",)),)))
    register(Section("shared", "Shared", 10, "box", (destination("second", ("second",)),)))

    shared = next(section for section in sections() if section.slug == "shared")
    assert [item.key for item in shared.destinations] == ["first", "second"]


def test_duplicate_route_ownership_is_rejected():
    register(Section("one", "One", 10, "one", (destination(),)))

    with pytest.raises(ValueError, match="route already registered"):
        register(Section("two", "Two", 20, "two", (destination("other"),)))


def test_deep_route_activates_its_logical_destination():
    register(Section("content", "Content", 10, "files", (destination(),)))
    request = SimpleNamespace(
        resolver_match=SimpleNamespace(url_name="studio_item_detail"),
        user=SimpleNamespace(is_superuser=False),
    )

    state = active_state(request)

    assert state["active_section"] == "content"
    assert state["active_destination"] == "items"
    content = next(row for row in state["sections"] if row["section"].slug == "content")
    assert content["active"] is True
    assert content["destinations"][0]["active"] is True


def test_superuser_destinations_are_hidden_from_staff():
    protected = Destination(
        "keys", "Keys", "studio_dashboard", ("studio_keys",), 10, superuser_only=True
    )
    register(Section("security", "Security", 10, "key", (protected,)))
    request = SimpleNamespace(
        resolver_match=SimpleNamespace(url_name="studio_dashboard"),
        user=SimpleNamespace(is_superuser=False),
    )

    state = active_state(request)

    security = next(row for row in state["sections"] if row["section"].slug == "security")
    assert security["destinations"] == []


def group(key="triggers", order=10, destinations=None):
    children = destinations or (
        destination(
            key="trigger_list",
            routes=("studio_trigger_list", "studio_trigger_detail"),
            order=10,
        ),
    )
    return DestinationGroup(key=key, title=key.title(), order=order, destinations=children)


def test_groups_are_sorted_with_their_destinations():
    register(
        Section(
            "ops",
            "Ops",
            90,
            "settings",
            destinations=(destination("flat", routes=("studio_flat",), order=10),),
            groups=(
                group("later", 20, (destination("z", routes=("studio_z",), order=20),)),
                group("earlier", 10, (destination("a", routes=("studio_a",), order=10),)),
            ),
        )
    )

    ops = next(section for section in sections() if section.slug == "ops")

    assert [item.key for item in ops.groups] == ["earlier", "later"]
    assert [item.key for item in ops.groups[0].destinations] == ["a"]
    assert [item.key for item in ops.destinations] == ["flat"]


def test_matching_group_metadata_merges_app_destinations():
    register(Section("ops", "Ops", 90, "settings", groups=(group("triggers"),)))
    register(
        Section(
            "ops",
            "Ops",
            90,
            "settings",
            groups=(group("triggers", destinations=(destination("second", ("second",)),)),),
        )
    )

    ops = next(section for section in sections() if section.slug == "ops")

    assert [item.key for item in ops.groups[0].destinations] == ["second", "trigger_list"]


def test_group_conflicts_are_rejected():
    register(Section("ops", "Ops", 90, "settings", groups=(group("triggers"),)))

    with pytest.raises(ValueError, match="destination group conflicts"):
        register(
            Section(
                "ops",
                "Ops",
                90,
                "settings",
                groups=(DestinationGroup("triggers", "Other", 10),),
            )
        )


def test_duplicate_group_keys_are_rejected():
    with pytest.raises(ValueError, match="destination group already registered"):
        register(
            Section("ops", "Ops", 90, "settings", groups=(group("triggers"), group("triggers")))
        )


def test_group_route_conflicts_are_rejected():
    register(Section("one", "One", 10, "one", (destination(),)))

    with pytest.raises(ValueError, match="route already registered"):
        register(
            Section(
                "two",
                "Two",
                20,
                "two",
                groups=(group("triggers", destinations=(destination(key="clashing"),)),),
            )
        )


def test_deep_route_activates_its_group():
    register(Section("ops", "Ops", 90, "settings", groups=(group("triggers"),)))
    request = SimpleNamespace(
        resolver_match=SimpleNamespace(url_name="studio_trigger_detail"),
        user=SimpleNamespace(is_superuser=False),
    )

    state = active_state(request)

    assert state["active_section"] == "ops"
    assert state["active_destination"] == "trigger_list"
    ops = next(row for row in state["sections"] if row["section"].slug == "ops")
    assert ops["active"] is True
    assert ops["groups"][0]["active"] is True
    assert ops["groups"][0]["destinations"][0]["active"] is True


def test_superuser_group_destinations_follow_destination_rules():
    protected_group = group(
        "keys",
        destinations=(
            Destination(
                "keys", "Keys", "studio_dashboard", ("studio_keys",), 10, superuser_only=True
            ),
        ),
    )
    register(Section("security", "Security", 10, "key", groups=(protected_group,)))

    staff_request = SimpleNamespace(
        resolver_match=SimpleNamespace(url_name="studio_dashboard"),
        user=SimpleNamespace(is_superuser=False),
    )
    superuser_request = SimpleNamespace(
        resolver_match=SimpleNamespace(url_name="studio_dashboard"),
        user=SimpleNamespace(is_superuser=True),
    )

    staff_state = active_state(staff_request)
    security = next(row for row in staff_state["sections"] if row["section"].slug == "security")
    assert security["groups"] == []

    superuser_state = active_state(superuser_request)
    security = next(row for row in superuser_state["sections"] if row["section"].slug == "security")
    assert [item["destination"].key for item in security["groups"][0]["destinations"]] == ["keys"]
