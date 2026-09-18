"""The `body_start` hook and the `main-content` landmark id a skip link targets."""

from types import SimpleNamespace

from django.template import engines
from django.template.loader import render_to_string

SKIP_LINK = '<a class="skip-link" href="#main-content">Skip to content</a>'


def shell_request(route_name="studio_dashboard"):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=False),
        session={},
    )


def render_shell():
    return render_to_string("community_base/studio/base.html", {"request": shell_request()})


def render_child(body):
    template = engines["django"].from_string(
        '{% extends "community_base/studio/base.html" %}'
        "{% block body_start %}" + body + "{% endblock %}"
    )
    return template.render({"request": shell_request()})


def body_start_region(html):
    """Everything between `<body ...>` and the first element the shell renders itself."""
    return html.split("<body", 1)[1].split(">", 1)[1].split('<div class="flex min-h-screen">', 1)[0]


def test_the_body_start_hook_is_empty_until_a_site_fills_it():
    assert body_start_region(render_shell()).strip() == ""


def test_a_site_skip_link_renders_as_the_first_thing_inside_body():
    html = render_child(SKIP_LINK)

    assert SKIP_LINK in body_start_region(html)
    assert html.index("skip-link") < html.index("studio-sidebar-toggle")
    assert html.index("skip-link") < html.index("<main")


def test_the_hook_sits_above_the_impersonation_banner_and_the_sidebar():
    html = render_child('<div data-testid="site-body-start">x</div>')
    region = body_start_region(html)

    assert 'data-testid="site-body-start"' in region
    assert "studio-impersonation" not in region.split("site-body-start", 1)[0]


def test_the_main_landmark_carries_the_id_a_skip_link_targets():
    html = render_shell()

    assert '<main id="main-content"' in html
    assert html.count('id="main-content"') == 1


def test_the_main_landmark_is_programmatically_focusable():
    # Without `tabindex="-1"` a skip link moves the viewport but not focus in several browsers.
    main_tag = render_shell().split("<main", 1)[1].split(">", 1)[0]

    assert 'tabindex="-1"' in main_tag


def test_the_skip_link_target_resolves_to_the_main_landmark():
    html = render_child(SKIP_LINK)
    target = html.split('href="#', 1)[1].split('"', 1)[0]

    assert f'<main id="{target}"' in html


def test_the_shell_ships_no_skip_link_of_its_own():
    # A site owns its skip-link markup and styling; the package renders nothing by default so a
    # site that overrides nothing is byte-identical to the shell before this hook existed.
    assert "skip-link" not in render_shell()


def test_the_landmark_keeps_the_classes_and_position_it_had_before_the_id():
    html = render_shell()

    assert '<main id="main-content" tabindex="-1" class="min-w-0 flex-1 overflow-hidden">' in html
    assert '<body class="bg-background text-foreground">' in html
    assert html.index("</aside>") < html.index("<main")
