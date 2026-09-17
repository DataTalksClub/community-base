"""The full-bleed banner hook above the Studio content region."""

from types import SimpleNamespace

from django.template import engines
from django.template.loader import render_to_string

CONTENT_COLUMN = '<div class="p-4 pt-16 md:p-8">'


def shell_request(route_name="studio_dashboard"):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=False),
        session={},
    )


def render_child(blocks):
    template = engines["django"].from_string(
        '{% extends "community_base/studio/base.html" %}' + blocks
    )
    return template.render({"request": shell_request()})


def above_the_content_column(html):
    return html.split("<main", 1)[1].split(CONTENT_COLUMN, 1)[0]


def test_the_banner_hook_is_empty_until_a_site_fills_it():
    html = render_to_string("community_base/studio/base.html", {"request": shell_request()})

    assert above_the_content_column(html).split(">", 1)[1].strip() == ""


def test_a_site_banner_renders_full_bleed_above_the_content_region():
    html = render_child(
        "{% block studio_banner %}"
        '<div data-testid="env-mismatch-banner">Staging data</div>'
        "{% endblock %}"
        "{% block content %}<p>Dashboard</p>{% endblock %}"
    )

    assert 'data-testid="env-mismatch-banner"' in above_the_content_column(html)
    assert html.index("env-mismatch-banner") < html.index(CONTENT_COLUMN)
    assert html.index(CONTENT_COLUMN) < html.index("<p>Dashboard</p>")


def test_the_content_block_still_renders_inside_the_padded_column():
    html = render_child("{% block content %}<p>Dashboard</p>{% endblock %}")

    assert "<p>Dashboard</p>" not in above_the_content_column(html)
