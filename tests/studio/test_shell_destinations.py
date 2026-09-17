"""External-link and icon destination fields, and their default behaviour."""

from types import SimpleNamespace

from django.template.loader import render_to_string

from community_base.studio.registry import Destination, Section, active_state, register
from community_base.studio.route_checks import route_claims


def shell_request(route_name="studio_dashboard", is_superuser=False):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=is_superuser),
        session={},
    )


def register_api_section():
    register(
        Section(
            "api-extras",
            "API extras",
            500,
            "settings",
            (
                Destination(
                    key="api_docs",
                    title="API docs",
                    url_name="",
                    route_names=(),
                    order=10,
                    icon="file-json",
                    external_url="/api/docs",
                    new_tab=True,
                ),
                Destination(
                    key="api_tokens",
                    title="API tokens",
                    url_name="studio_dashboard",
                    route_names=("studio_api_token_list",),
                    order=20,
                    icon="key",
                ),
            ),
        )
    )


def link_markup(html, title):
    return html.split(f">{title}<", 1)[0].rsplit("<li>", 1)[1]


def test_an_external_destination_links_off_the_urlconf_in_a_new_tab():
    register_api_section()

    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})
    fragment = link_markup(html, "API docs")

    assert 'href="/api/docs"' in fragment
    assert 'target="_blank" rel="noopener"' in fragment
    assert 'data-lucide="external-link"' in html.split("API docs", 1)[1].split("</a>", 1)[0]


def test_an_external_destination_claims_no_route_and_is_never_active():
    register_api_section()

    state = active_state(shell_request())
    section = next(item for item in state["sections"] if item["section"].slug == "api-extras")
    docs = next(row for row in section["destinations"] if row["destination"].key == "api_docs")

    assert docs["active"] is False
    assert "api-extras/api_docs" not in str(route_claims())


def test_a_destination_icon_renders_next_to_its_label():
    register_api_section()

    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert 'data-lucide="file-json"' in link_markup(html, "API docs")
    assert 'data-lucide="key"' in link_markup(html, "API tokens")


def test_destinations_without_the_new_fields_render_exactly_as_before():
    register(
        Section(
            "plain",
            "Plain",
            501,
            "settings",
            (
                Destination(
                    key="plain_one",
                    title="Plain one",
                    url_name="studio_dashboard",
                    route_names=("studio_plain_one",),
                    order=10,
                ),
            ),
        )
    )

    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})
    fragment = link_markup(html, "Plain one")

    assert "data-lucide" not in fragment
    assert "target=" not in fragment
    assert "rel=" not in fragment
    assert 'href="/studio/"' in fragment


def test_a_destination_with_neither_url_name_nor_external_url_is_skipped():
    register(
        Section(
            "broken",
            "Broken",
            502,
            "settings",
            (
                Destination(
                    key="broken_one",
                    title="Broken one",
                    url_name="",
                    route_names=(),
                    order=10,
                ),
            ),
        )
    )

    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert "Broken one" not in html
