"""The sidebar footer hook, and the fact that it ships empty."""

from types import SimpleNamespace

from django.template import engines
from django.template.loader import render_to_string


def shell_request(route_name="studio_dashboard"):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=False),
        session={},
    )


def render_child(body):
    template = engines["django"].from_string(
        '{% extends "community_base/studio/base.html" %}'
        "{% block studio_sidebar_footer %}" + body + "{% endblock %}"
    )
    return template.render({"request": shell_request()})


def test_the_sidebar_footer_is_empty_until_a_site_fills_it():
    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})
    footer = html.split("</nav>", 1)[1].split("</aside>", 1)[0]

    assert footer.strip() == ""


def test_a_site_renders_its_own_version_line_and_links_in_the_footer():
    html = render_child(
        '<p class="px-3 text-xs">v1.2.3</p>'
        '<a href="/">Back to website</a>'
        '<button type="button" data-studio-theme-toggle>Theme</button>'
    )
    footer = html.split("</nav>", 1)[1].split("</aside>", 1)[0]

    assert "v1.2.3" in footer
    assert "Back to website" in footer
    assert "data-studio-theme-toggle" in footer


def test_the_shell_ships_no_theme_toggle_of_its_own():
    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert "data-studio-theme-toggle" not in html


def test_the_shell_reads_the_stored_theme_behind_a_guard():
    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})
    head_script = html.split("<script>", 1)[1].split("</script>", 1)[0]

    assert "try {" in head_script
    assert "catch (error)" in head_script
