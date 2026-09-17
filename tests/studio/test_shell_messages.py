"""The messages region: overridable by a site, tagged and selectable by default."""

from types import SimpleNamespace

from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template import engines
from django.template.loader import render_to_string


def shell_request(route_name="studio_dashboard"):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=False),
        session={},
    )


def render_shell(messages=()):
    return render_to_string(
        "community_base/studio/base.html",
        {"request": shell_request(), "messages": list(messages)},
    )


def render_child(body, messages=()):
    template = engines["django"].from_string(
        '{% extends "community_base/studio/base.html" %}'
        "{% block studio_messages %}" + body + "{% endblock %}"
    )
    return template.render({"request": shell_request(), "messages": list(messages)})


def test_the_default_region_carries_a_test_id():
    html = render_shell([Message(constants.SUCCESS, "Saved.")])

    assert 'data-testid="messages-region"' in html
    assert "Saved." in html


def test_the_default_region_carries_each_message_tag():
    html = render_shell(
        [
            Message(constants.SUCCESS, "Saved."),
            Message(constants.ERROR, "Nope.", extra_tags="toast"),
        ]
    )

    assert 'data-message-tag="success"' in html
    assert 'data-message-tag="toast error"' in html


def test_the_default_region_distinguishes_success_from_error():
    success = render_shell([Message(constants.SUCCESS, "Saved.")])
    error = render_shell([Message(constants.ERROR, "Nope.")])

    assert "bg-green-500/20" in success
    assert "bg-red-500/20" not in success
    assert "bg-red-500/20" in error
    assert "bg-green-500/20" not in error


def test_a_message_with_no_known_level_keeps_the_neutral_card_look():
    html = render_shell([Message(42, "Odd.")])
    region = html.split('data-testid="messages-region"', 1)[1].split("</div>", 1)[0]

    assert "bg-card" in region
    assert "text-foreground" in region


def test_the_shell_renders_no_region_without_messages():
    html = render_shell()

    assert 'data-testid="messages-region"' not in html
    assert "aria-live" not in html


def test_a_site_region_replaces_the_package_one_entirely():
    html = render_child(
        '{% if messages %}<div data-testid="messages-region">'
        "{% for message in messages %}"
        '<div data-message-tag="{{ message.tags }}">{{ message }}</div>'
        "{% endfor %}</div>{% endif %}",
        [Message(constants.SUCCESS, "Saved.")],
    )

    assert html.count('data-testid="messages-region"') == 1
    assert "bg-green-500/20" not in html
    assert "aria-live" not in html
    assert '<div data-message-tag="success">Saved.</div>' in html


def test_a_site_can_suppress_the_region_altogether():
    html = render_child("", [Message(constants.SUCCESS, "Saved.")])

    assert "messages-region" not in html
    assert "Saved." not in html
