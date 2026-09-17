"""Sidebar section collapse: density rule, active-section guarantee, fallbacks."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string

from community_base.studio import registry
from community_base.studio.registry import Destination, Section, active_state, register

NAV_SCRIPT = Path(registry.__file__).resolve().parent / "static/community_base/studio-nav.js"


def shell_request(route_name="studio_dashboard", is_superuser=False):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=is_superuser),
        session={},
    )


def register_dense_registry(sections=11, per_section=5):
    """Register 11 sections carrying 55 destinations, past AISL's 51."""

    for section_index in range(sections):
        slug = f"dense{section_index}"
        register(
            Section(
                slug,
                f"Dense {section_index}",
                500 + section_index,
                "settings",
                tuple(
                    Destination(
                        key=f"{slug}_{row}",
                        title=f"Dense {section_index} {row}",
                        url_name="studio_dashboard",
                        route_names=(
                            f"studio_{slug}_{row}_list",
                            f"studio_{slug}_{row}_detail",
                        ),
                        order=row,
                    )
                    for row in range(per_section)
                ),
            )
        )


def register_sparse_registry():
    register(
        Section(
            "sparse",
            "Sparse",
            500,
            "settings",
            (
                Destination(
                    key="sparse_one",
                    title="Sparse one",
                    url_name="studio_dashboard",
                    route_names=("studio_sparse_one",),
                    order=10,
                ),
            ),
        )
    )


def section_markup(html, slug):
    return html.split(f'data-studio-section="{slug}"', 1)[1].split("</section>", 1)[0]


def toggle_states(html):
    return dict(
        re.findall(
            r'data-studio-section-key="([^"]+)"[^>]*\n\s*(?:data-studio-section-active="true"\n\s*)?'
            r'aria-controls="[^"]+"\n\s*aria-expanded="([^"]+)"',
            html,
        )
    )


def run_node(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed; the sidebar script cannot be executed here")
    program = (
        "const fs = require('fs');\n"
        f"const source = fs.readFileSync({json.dumps(str(NAV_SCRIPT))}, 'utf8');\n"
        "const window = {};\n"
        "new Function('window', source)(window);\n"
        "const studioNav = window.studioNav;\n" + body
    )
    completed = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def test_a_dense_registry_renders_every_inactive_section_collapsed():
    register_dense_registry()

    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})
    states = toggle_states(html)

    assert len(states) == 19
    assert states["dense0"] == "false"
    assert states["dense10"] == "false"
    assert set(states.values()) == {"false"}
    assert " hidden>" in section_markup(html, "dense0")


def test_a_dense_registry_keeps_the_active_section_open():
    register_dense_registry()

    html = render_to_string(
        "community_base/studio/base.html", {"request": shell_request("studio_dense7_2_list")}
    )
    states = toggle_states(html)

    assert states["dense7"] == "true"
    assert states["dense6"] == "false"
    fragment = section_markup(html, "dense7")
    assert 'id="studio-section-dense7">' in fragment
    assert 'aria-current="page"' in fragment


def test_a_dense_registry_keeps_the_active_deep_routes_section_open():
    register_dense_registry()

    html = render_to_string(
        "community_base/studio/base.html", {"request": shell_request("studio_dense3_4_detail")}
    )

    assert toggle_states(html)["dense3"] == "true"
    fragment = section_markup(html, "dense3")
    assert 'id="studio-section-dense3">' in fragment
    assert 'data-studio-section-active="true"' in fragment


def test_a_sparse_registry_renders_every_section_expanded():
    register_sparse_registry()

    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})
    states = toggle_states(html)

    assert set(states.values()) == {"true"}
    assert " hidden>" not in html
    assert "-rotate-90" not in html


def test_the_collapse_threshold_is_configurable(settings):
    settings.COMMUNITY_BASE = {"STUDIO_NAV_COLLAPSE_THRESHOLD": 0}
    register_sparse_registry()

    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert toggle_states(html)["sparse"] == "false"


def test_untitled_sections_never_collapse():
    register_dense_registry()

    state = active_state(shell_request())
    home = next(item for item in state["sections"] if item["section"].slug == "home")

    assert home["collapsible"] is False
    assert home["expanded"] is True


def test_the_active_section_stays_open_over_a_stored_collapse():
    assert run_node(
        "console.log(JSON.stringify("
        "studioNav.resolveExpanded({people: false}, 'people', false, 'people')"
        "));"
    )


def test_a_stored_preference_beats_the_rendered_state_for_other_sections():
    assert run_node(
        "console.log(JSON.stringify(["
        "studioNav.resolveExpanded({people: true}, 'people', false, 'events'),"
        "studioNav.resolveExpanded({people: false}, 'people', true, 'events'),"
        "studioNav.resolveExpanded({}, 'people', true, 'events')"
        "]));"
    ) == [True, False, True]


def test_unavailable_storage_falls_back_to_the_rendered_state():
    assert run_node(
        """
        const blocked = {
          getItem() { throw new Error('storage is blocked'); },
          setItem() { throw new Error('storage is blocked'); }
        };
        const results = [
          studioNav.readPreferences(blocked),
          studioNav.readPreferences(null),
          studioNav.readPreferences({getItem: () => 'not json'}),
          studioNav.readPreferences({getItem: () => '[1,2]'}),
          studioNav.readPreferences({getItem: () => null}),
          studioNav.writePreference(blocked, 'people', true),
          studioNav.writePreference(null, 'people', true),
          studioNav.resolveExpanded(studioNav.readPreferences(blocked), 'people', true, ''),
          studioNav.resolveExpanded(studioNav.readPreferences(blocked), 'people', false, '')
        ];
        console.log(JSON.stringify(results));
        """
    ) == [{}, {}, {}, {}, {}, False, False, True, False]


def test_a_working_storage_round_trips_a_preference():
    assert run_node(
        """
        let cell = null;
        const storage = {
          getItem: () => cell,
          setItem: (key, value) => { cell = value; }
        };
        studioNav.writePreference(storage, 'people', false);
        studioNav.writePreference(storage, 'events', true);
        console.log(JSON.stringify([
          studioNav.readPreferences(storage),
          studioNav.resolveExpanded(studioNav.readPreferences(storage), 'people', true, '')
        ]));
        """
    ) == [{"people": False, "events": True}, False]
