"""System checks that keep the Studio content-block contract from failing silently.

Every shared Studio page template fills its body inside two nested blocks,
``content`` wrapping ``studio_content`` (see ``community_base/studio/base.html``). A
consuming site is free to replace ``community_base/studio/base.html`` outright with its
own shell, as AI-Shipping-Labs/website and DataTalksClub/website both do today, but that
replacement must expose a reachable slot for at least one of the two names. If it exposes
neither, every shared Studio page renders as an empty shell: HTTP 200, a correct title,
no body, and nothing in the response to say why (community-base#279).

This check renders two tiny probe templates that extend the resolved
``community_base/studio/base.html`` and each override one of the two contracted block
names with a sentinel string. Using the real template engine, rather than walking the
compiled node tree by hand, answers the only question that matters: would a shared page's
override actually reach the page. If neither probe's sentinel comes back, the site's
Studio base does not honour the contract and this check fails loudly, at ``manage.py
check`` time, rather than the failure staying invisible in a rendered page.
"""

from django.core.checks import CheckMessage, Error, Tags, register
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.template import engines as template_engines

CONTRACT_BLOCK_NAMES = ("content", "studio_content")

_SENTINEL = "community-base-studio-content-check-sentinel"

_PROBE_SOURCE = '{{% extends "community_base/studio/base.html" %}}{{% block {block_name} %}}{sentinel}{{% endblock %}}'  # noqa: E501


def _reachable_block_names() -> set[str]:
    """Return the subset of `CONTRACT_BLOCK_NAMES` that the resolved Studio base honours."""
    engine = template_engines["django"]
    reachable: set[str] = set()
    for block_name in CONTRACT_BLOCK_NAMES:
        source = _PROBE_SOURCE.format(block_name=block_name, sentinel=_SENTINEL)
        try:
            template = engine.from_string(source)
            rendered = template.render({})
        except (TemplateDoesNotExist, TemplateSyntaxError):
            continue
        except Exception:  # noqa: BLE001 - a broken site shell must not crash `check`
            continue
        if _SENTINEL in rendered:
            reachable.add(block_name)
    return reachable


@register(Tags.templates)
def check_studio_content_block_contract(app_configs, **kwargs) -> list[CheckMessage]:
    """Fail loudly when the resolved Studio base exposes neither contracted block.

    Every shared Studio content template fills both ``content`` and ``studio_content``,
    nested, so a site's Studio base only needs to expose one of the two names as a
    reachable block slot. A site that has replaced ``community_base/studio/base.html``
    with a shell that names its content region something else entirely gets this error
    instead of a silently empty page.
    """
    if _reachable_block_names():
        return []
    return [
        Error(
            "The Studio base template resolved for 'community_base/studio/base.html' "
            "does not expose a reachable 'content' or 'studio_content' block. Every "
            "shared Studio page template fills its body inside both, nested, so a site "
            "that overrides this template path must expose at least one of them as a "
            "block a child template can reach, or shared Studio pages render as an "
            "empty shell with no error (community-base#279).",
            hint=(
                "Add {% block content %} or {% block studio_content %} to the template "
                "that now resolves for 'community_base/studio/base.html', or stop "
                "overriding that path and let the site use the package shell "
                "directly. See docs/02-architecture.md section 4 and "
                "community_base/studio/README.md, 'Templates'."
            ),
            id="community_base.studio.E001",
        )
    ]
