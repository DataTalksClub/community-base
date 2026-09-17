"""The quick-jump overlay: one Ctrl/Cmd-K palette over the sidebar's own search."""

from types import SimpleNamespace

from django.template import engines
from django.template.loader import render_to_string

SIDEBAR_SEARCH_BOX = (
    '<div class="relative mb-5" data-studio-search data-endpoint="/studio/search/">\n'
    '      <label for="studio-search" class="sr-only">Search Studio</label>\n'
    '      <input id="studio-search" type="search" autocomplete="off" placeholder="Search Studio"\n'
    '             class="w-full rounded-lg border border-border bg-secondary px-3 py-2 text-sm"\n'
    '             aria-controls="studio-search-results" aria-expanded="false">\n'
    '      <div id="studio-search-results"\n'
    '           class="absolute inset-x-0 top-full z-50 mt-1 hidden max-h-80 overflow-y-auto '
    'rounded-lg border border-border bg-card shadow-lg"></div>\n'
    "    </div>"
)


def shell_request(route_name="studio_dashboard"):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=False),
        session={},
    )


def render_shell():
    return render_to_string("community_base/studio/base.html", {"request": shell_request()})


def test_the_overlay_renders_hidden_by_default():
    html = render_shell()

    assert 'id="studio-quick-jump"' in html
    assert "data-studio-quick-jump" in html
    assert 'data-testid="studio-quick-jump"' in html
    overlay = html.split('id="studio-quick-jump"', 1)[1].split(">", 1)[0]
    assert "hidden" in overlay
    assert "flex" not in overlay


def test_the_overlay_carries_a_dialog_role_and_its_own_title():
    html = render_shell()

    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert "Quick jump" in html


def test_the_overlay_input_and_results_carry_their_test_ids_and_aria_roles():
    html = render_shell()

    assert 'id="studio-quick-jump-input"' in html
    assert 'data-testid="studio-quick-jump-input"' in html
    assert 'role="combobox"' in html
    assert 'id="studio-quick-jump-results"' in html
    assert 'data-testid="studio-quick-jump-results"' in html
    assert 'role="listbox"' in html


def test_the_overlay_reuses_the_sidebars_own_search_endpoint():
    html = render_shell()

    endpoints = [
        chunk.split('data-endpoint="', 1)[1].split('"', 1)[0]
        for chunk in html.split("data-studio-search")[1:]
    ]

    assert endpoints == ["/studio/search/", "/studio/search/"]


def test_the_sidebar_search_box_markup_is_unchanged():
    html = render_shell()

    assert SIDEBAR_SEARCH_BOX in html


def test_a_site_can_remove_the_overlay_and_the_sidebar_search_box_still_renders():
    template = engines["django"].from_string(
        '{% extends "community_base/studio/base.html" %}{% block studio_quick_jump %}{% endblock %}'
    )

    html = template.render({"request": shell_request()})

    assert "studio-quick-jump" not in html
    assert SIDEBAR_SEARCH_BOX in html


def test_the_compatibility_template_carries_the_overlay_too():
    html = render_to_string("studio/base.html", {"request": shell_request()})

    assert 'id="studio-quick-jump"' in html
    assert SIDEBAR_SEARCH_BOX in html
