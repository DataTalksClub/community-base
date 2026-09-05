from community_base.studio.providers import (
    dashboard_cards,
    register_card_provider,
    register_search_provider,
    search_results,
)


def test_search_providers_are_merged_by_group():
    register_search_provider("people", lambda request, query: {"people": [{"label": query}]})
    register_search_provider("pages", lambda request, query: {"pages": [{"label": "Settings"}]})
    register_search_provider("more-people", lambda request, query: {"people": [{"label": "Two"}]})

    assert search_results(object(), "Ada") == {
        "people": [{"label": "Ada"}, {"label": "Two"}],
        "pages": [{"label": "Settings"}],
    }


def test_dashboard_providers_flatten_cards_in_registration_order():
    register_card_provider("count", lambda request: {"title": "Members", "value": 12})
    register_card_provider("health", lambda request: [{"title": "Mail"}, {"title": "Jobs"}])

    assert [card["title"] for card in dashboard_cards(object())] == ["Members", "Mail", "Jobs"]
