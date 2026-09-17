"""The mobile sidebar scroll affordance: a gradient hint at the foot of the nav."""

from types import SimpleNamespace

from django.template import engines
from django.template.loader import render_to_string


def shell_request(route_name="studio_dashboard"):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=False),
        session={},
    )


def render_shell():
    return render_to_string("community_base/studio/base.html", {"request": shell_request()})


def test_the_affordance_renders_hidden_by_default_with_a_gradient():
    html = render_shell()

    assert 'id="studio-sidebar-scroll-affordance"' in html
    affordance = html.split('id="studio-sidebar-scroll-affordance"', 1)[1].split(">", 1)[0]
    assert "hidden" in affordance
    assert "bg-gradient-to-t" in affordance
    assert "from-card" in affordance
    assert "to-transparent" in affordance
    assert "md:hidden" in affordance
    assert 'aria-hidden="true"' in affordance


def test_the_affordance_is_inert_to_pointer_events():
    html = render_shell()

    affordance = html.split('id="studio-sidebar-scroll-affordance"', 1)[1].split(">", 1)[0]
    assert "pointer-events-none" in affordance


def test_the_affordance_sits_at_the_foot_of_the_nav_not_the_sidebar_footer():
    html = render_shell()
    before_nav_close = html.split("</nav>", 1)[0]
    after_nav_close = html.split("</nav>", 1)[1].split("</aside>", 1)[0]

    assert "studio-sidebar-scroll-affordance" in before_nav_close
    assert "studio-sidebar-scroll-affordance" not in after_nav_close


def test_the_sidebar_footer_hook_stays_empty_alongside_the_affordance():
    html = render_shell()
    footer = html.split("</nav>", 1)[1].split("</aside>", 1)[0]

    assert footer.strip() == ""


def test_a_site_overriding_the_footer_still_gets_the_affordance_inside_nav():
    template = engines["django"].from_string(
        '{% extends "community_base/studio/base.html" %}'
        "{% block studio_sidebar_footer %}<p>v1.0</p>{% endblock %}"
    )

    html = template.render({"request": shell_request()})
    before_nav_close = html.split("</nav>", 1)[0]

    assert "studio-sidebar-scroll-affordance" in before_nav_close
    assert "<p>v1.0</p>" in html
