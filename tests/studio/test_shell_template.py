from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import override_settings

from community_base.studio.registry import Destination, DestinationGroup, Section, register


def shell_request(route_name="studio_dashboard", is_superuser=False):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=is_superuser),
        session={},
    )


def register_trigger_section():
    register(
        Section(
            "ops220",
            "Operations",
            90,
            "settings",
            groups=(
                DestinationGroup(
                    key="triggers",
                    title="Triggers",
                    order=10,
                    destinations=(
                        Destination(
                            key="trigger_list",
                            title="Triggers",
                            url_name="studio_dashboard",
                            route_names=("studio_trigger_detail",),
                            order=10,
                        ),
                    ),
                ),
            ),
        )
    )


def test_shell_renders_nested_groups_open_on_active_routes():
    register_trigger_section()

    html = render_to_string(
        "community_base/studio/base.html", {"request": shell_request("studio_trigger_detail")}
    )

    assert "<details" in html
    assert 'data-studio-group="triggers" open>' in html
    fragment = html.split('data-studio-group="triggers"', 1)[1].split("</details>", 1)[0]
    assert 'aria-current="page"' in fragment


def test_shell_renders_inactive_groups_closed():
    register_trigger_section()

    html = render_to_string(
        "community_base/studio/base.html", {"request": shell_request("studio_dashboard")}
    )

    assert '<details class="studio-nav-group" data-studio-group="triggers">' in html
    fragment = html.split('data-studio-group="triggers"', 1)[1].split("</details>", 1)[0]
    assert "aria-current" not in fragment


@override_settings(COMMUNITY_BASE={"STUDIO_EXTRA_CSS": ("css/site-studio.css",)})
def test_shell_loads_the_site_extension_stylesheet_after_its_own():
    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert "site-studio.css" in html
    assert html.index("community_base/studio.css") < html.index("site-studio.css")


def test_shell_loads_no_extension_stylesheet_by_default():
    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert "site-studio.css" not in html


def test_sidebar_shows_no_calendly_destination_while_the_flag_is_off():
    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert "Call hosts" not in html
    assert "Booked calls" not in html


def test_sidebar_lists_calendly_destinations_once_the_flag_turns_on(settings):
    settings.COMMUNITY_BASE = {"CALENDLY": True}

    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert "Call hosts" in html
    assert "Booked calls" in html
