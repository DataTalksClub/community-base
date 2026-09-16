from community_base.curriculum.apps import events_dependent_surfaces_active


def test_event_surfaces_require_the_package_events_app():
    assert events_dependent_surfaces_active(["community_base.events", "other"])
    assert not events_dependent_surfaces_active(
        ["events", "community_base.curriculum", "community_base.knowledge_base"]
    )
