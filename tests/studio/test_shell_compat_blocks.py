"""The AISL compatibility template carries the shell's hooks unchanged."""

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


def test_a_page_on_the_compatibility_template_overrides_the_new_blocks():
    template = engines["django"].from_string(
        '{% extends "studio/base.html" %}'
        '{% block studio_messages %}<div data-testid="site-messages"></div>{% endblock %}'
        '{% block studio_banner %}<div data-testid="site-banner"></div>{% endblock %}'
    )

    html = template.render(
        {"request": shell_request(), "messages": [Message(constants.SUCCESS, "Saved.")]}
    )

    assert 'data-testid="site-messages"' in html
    assert 'data-testid="site-banner"' in html
    assert 'data-testid="messages-region"' not in html
    assert "Saved." not in html


def test_the_compatibility_template_keeps_the_default_region():
    html = render_to_string(
        "studio/base.html",
        {"request": shell_request(), "messages": [Message(constants.ERROR, "Nope.")]},
    )

    assert 'data-testid="messages-region"' in html
    assert 'data-message-tag="error"' in html
