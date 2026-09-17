"""The Studio content-block contract stops being silent (community-base#279).

`api_keys.html` used to fill only `{% block content %}`. AI-Shipping-Labs' own Studio
base replaces `community_base/studio/base.html` wholesale with a shell that only exposes
`{% block studio_content %}`; DataTalksClub's replacement only exposes `{% block content
%}`. Either site's replacement silently dropped the page body of every shared Studio
template that picked the other name -- HTTP 200, correct title, empty shell, no error
anywhere.

The fix has two parts, both exercised here:

- every shared Studio content template now fills its body inside both blocks, nested
  (`content` wrapping `studio_content`), so a site exposing either name renders the page
  unchanged, with no site-side template change required;
- `community_base.studio.checks.check_studio_content_block_contract` fails `manage.py
  check` with an actionable error when a site's replacement exposes neither name, so a
  genuinely incompatible override is caught at check time instead of rendering an
  unexplained empty page.
"""

import glob
import pathlib

import pytest
from django.template.loader import render_to_string
from django.test import override_settings

from community_base.studio.checks import check_studio_content_block_contract

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "community_base"

# The compatibility shim is a pure pass-through with no blocks of its own by design.
PASSTHROUGH_TEMPLATES = {PACKAGE_ROOT / "studio" / "templates" / "studio" / "base.html"}


def _studio_shell_pages():
    """Every package template that extends the shared Studio shell and has a body."""
    pages = []
    for match in glob.glob(str(PACKAGE_ROOT / "*" / "templates" / "**" / "*.html"), recursive=True):
        path = pathlib.Path(match)
        if path in PASSTHROUGH_TEMPLATES:
            continue
        text = path.read_text()
        if '{% extends "community_base/studio/base.html" %}' in text and "{% block" in text:
            pages.append(path)
    return pages


def _make_site_base(tmp_path, block_name):
    """Write a synthetic, replaced Studio base exposing only one block name."""
    base_dir = tmp_path / "templates" / "community_base" / "studio"
    base_dir.mkdir(parents=True)
    (base_dir / "base.html").write_text(
        f"<!doctype html><html><body>{{% block {block_name} %}}{{% endblock %}}</body></html>"
    )
    return tmp_path / "templates"


def _templates_with_dir(settings, extra_dir):
    templates = [dict(settings.TEMPLATES[0])]
    templates[0]["DIRS"] = [str(extra_dir), *templates[0]["DIRS"]]
    return templates


# ---------------------------------------------------------------------------
# Every shipped Studio content template nests both contracted block names.
# ---------------------------------------------------------------------------


def test_every_studio_shell_page_fills_both_contracted_block_names():
    pages = _studio_shell_pages()
    assert len(pages) >= 60, "expected the known set of Studio content templates"

    missing = [
        path
        for path in pages
        if "{% block content %}" not in path.read_text()
        or "{% block studio_content %}" not in path.read_text()
    ]

    assert missing == [], (
        "every Studio content template must fill its body inside both {% block content %} "
        "and {% block studio_content %}, nested, so a site exposing either name alone "
        "still renders the page (see docs/02-architecture.md section 4)"
    )


# ---------------------------------------------------------------------------
# A site exposing only one of the two names renders unchanged -- no site-side change.
# ---------------------------------------------------------------------------


def test_a_site_replacement_exposing_only_studio_content_still_renders_api_keys(tmp_path, settings):
    """Reproduces AI-Shipping-Labs' own Studio shell: only `studio_content` is reachable."""
    site_dir = _make_site_base(tmp_path, "studio_content")

    with override_settings(TEMPLATES=_templates_with_dir(settings, site_dir)):
        html = render_to_string(
            "community_base/api/api_keys.html",
            {"form": None, "messages": [], "plaintext": None, "api_keys": []},
        )

    assert "Create API key" in html
    assert "No API keys." in html


def test_a_site_replacement_exposing_only_content_still_renders_api_keys(tmp_path, settings):
    """Reproduces DataTalksClub's own Studio shell: only `content` is reachable."""
    site_dir = _make_site_base(tmp_path, "content")

    with override_settings(TEMPLATES=_templates_with_dir(settings, site_dir)):
        html = render_to_string(
            "community_base/api/api_keys.html",
            {"form": None, "messages": [], "plaintext": None, "api_keys": []},
        )

    assert "Create API key" in html
    assert "No API keys." in html


def test_a_site_replacement_exposing_only_content_still_renders_a_studio_content_page(
    tmp_path, settings
):
    """The other half of the split: a page that used to fill only `studio_content`."""
    site_dir = _make_site_base(tmp_path, "content")

    with override_settings(TEMPLATES=_templates_with_dir(settings, site_dir)):
        html = render_to_string("comments/studio/comment_list.html", {"q": "", "comments": []})

    assert "<h1>Comments</h1>" in html
    assert "No comments." in html


def test_a_site_replacement_exposing_only_studio_content_still_renders_a_content_page(
    tmp_path, settings
):
    """The other half of the split, the other direction: a `content`-only page."""
    site_dir = _make_site_base(tmp_path, "studio_content")

    with override_settings(TEMPLATES=_templates_with_dir(settings, site_dir)):
        html = render_to_string("comments/studio/comment_list.html", {"q": "", "comments": []})

    assert "<h1>Comments</h1>" in html
    assert "No comments." in html


# ---------------------------------------------------------------------------
# A site exposing neither name renders empty, and the system check catches it loudly.
# ---------------------------------------------------------------------------


def test_a_site_replacement_exposing_neither_name_renders_an_empty_page(tmp_path, settings):
    """What community-base#279 actually looked like: a genuinely incompatible shell."""
    site_dir = _make_site_base(tmp_path, "page_body")

    with override_settings(TEMPLATES=_templates_with_dir(settings, site_dir)):
        html = render_to_string(
            "community_base/api/api_keys.html",
            {"form": None, "messages": [], "plaintext": None, "api_keys": []},
        )

    # HTTP 200, no exception, and the body is gone -- exactly the silent failure the
    # issue reported. This is the case the system check below must not let through.
    assert "Create API key" not in html


def test_a_site_replacement_exposing_neither_name_fails_the_system_check(tmp_path, settings):
    site_dir = _make_site_base(tmp_path, "page_body")

    with override_settings(TEMPLATES=_templates_with_dir(settings, site_dir)):
        errors = check_studio_content_block_contract(app_configs=None)

    assert len(errors) == 1
    assert errors[0].id == "community_base.studio.E001"
    assert "content" in errors[0].msg
    assert "studio_content" in errors[0].msg


@pytest.mark.parametrize("block_name", ["content", "studio_content"])
def test_a_site_replacement_exposing_either_contracted_name_passes_the_system_check(
    tmp_path, settings, block_name
):
    site_dir = _make_site_base(tmp_path, block_name)

    with override_settings(TEMPLATES=_templates_with_dir(settings, site_dir)):
        errors = check_studio_content_block_contract(app_configs=None)

    assert errors == []


def test_the_package_shell_itself_passes_the_system_check():
    """The default, un-overridden package base exposes both names."""
    assert check_studio_content_block_contract(app_configs=None) == []
