"""Keyboard focus and per-destination selectors on every sidebar link."""

import re
from types import SimpleNamespace

from django.template.loader import render_to_string

from community_base.studio.registry import Destination, DestinationGroup, Section, register

FOCUS_RING = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"


def shell_request(route_name="studio_dashboard", is_superuser=True):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=is_superuser),
        session={},
    )


def register_mixed_section():
    register(
        Section(
            "ops715",
            "Operations",
            95,
            "settings",
            destinations=(
                Destination(
                    key="flat_destination",
                    title="Flat destination",
                    url_name="studio_dashboard",
                    route_names=("studio_flat_detail",),
                    order=10,
                ),
                Destination(
                    key="external_destination",
                    title="External destination",
                    url_name="",
                    route_names=(),
                    order=20,
                    external_url="/api/docs",
                    new_tab=True,
                ),
            ),
            groups=(
                DestinationGroup(
                    key="grouped715",
                    title="Grouped",
                    order=10,
                    destinations=(
                        Destination(
                            key="grouped_destination",
                            title="Grouped destination",
                            url_name="studio_dashboard",
                            route_names=("studio_grouped_detail",),
                            order=10,
                        ),
                    ),
                ),
            ),
        )
    )


def sidebar_nav(html):
    return html.split('<nav id="studio-sidebar-nav"', 1)[1].split("</nav>", 1)[0]


def nav_anchors(html):
    return re.findall(r"<a\b[^>]*>", sidebar_nav(html))


def render_shell(route_name="studio_dashboard"):
    return render_to_string(
        "community_base/studio/base.html", {"request": shell_request(route_name)}
    )


def test_every_nav_anchor_carries_the_focus_ring():
    register_mixed_section()

    anchors = nav_anchors(render_shell())

    assert anchors
    assert [anchor for anchor in anchors if FOCUS_RING not in anchor] == []


def test_the_active_nav_anchor_carries_the_focus_ring_too():
    register_mixed_section()

    anchors = nav_anchors(render_shell("studio_flat_detail"))
    active = [anchor for anchor in anchors if 'aria-current="page"' in anchor]

    assert len(active) == 1
    assert FOCUS_RING in active[0]


def test_every_destination_carries_a_test_id_derived_from_its_key():
    register_mixed_section()

    html = render_shell()

    for key in ("flat_destination", "external_destination", "grouped_destination"):
        assert f'data-testid="studio-nav-{key}"' in html


def test_every_nav_anchor_carries_a_test_id():
    register_mixed_section()

    anchors = nav_anchors(render_shell())

    assert [anchor for anchor in anchors if 'data-testid="studio-nav-' not in anchor] == []


def test_the_test_id_does_not_move_when_the_destination_becomes_active():
    register_mixed_section()

    inactive = render_shell()
    active = render_shell("studio_flat_detail")

    assert 'data-testid="studio-nav-flat_destination"' in inactive
    assert 'data-testid="studio-nav-flat_destination"' in active
