from types import SimpleNamespace

import pytest

from community_base.studio.registry import Destination, Section, active_state, register, sections


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
