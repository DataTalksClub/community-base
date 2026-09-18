"""The public block contract stops being silent (C7.25).

Django drops the content of a block that no template in the inheritance chain defines: no
exception, no warning, nothing in the logs. Both adopting sites were losing a different
part of the five-block contract in `docs/02-architecture.md` section 5, and both pages
returned 200 and looked fine.

Two things are exercised here.

- The seam. Every shared public template now extends `community_base/public/base.html`
  rather than the site's own `base.html`, so a site whose chrome names those slots
  differently overrides one path instead of forking the pages. The shipped seam is a
  pass-through, and `test_the_seam_changes_nothing_for_a_conforming_site` renders all 41
  public templates twice, through the seam and directly against the same base, to show
  byte-identical output.
- The check. `community_base.kernel.checks.check_public_base_block_contract` reads the
  chain above the seam and reports every contracted block with nowhere to render, as an
  error for `content` and a warning for the other four.

The two synthetic bases below are shaped like the two real ones rather than invented: one
names its body slot `body` and its script slot `extra_scripts` and defines no `content`
(AI-Shipping-Labs/website), the other defines `content` and `extra_js` but answers robots
metadata under `meta_robots` and has no `meta_description` (DataTalksClub/website).
"""

import pathlib

import pytest
from django.core.checks import Error, Warning
from django.template import engines
from django.template.loader import render_to_string
from django.test import override_settings

from community_base.kernel.checks import check_public_base_block_contract
from community_base.kernel.template_contract import (
    BLOCK_CHECK_ID,
    PUBLIC_BASE_TEMPLATE,
    PUBLIC_TEMPLATES,
)
from tests.template_tree import public_templates

# Shaped like AI-Shipping-Labs/website's templates/base.html: `body` and `extra_scripts`,
# no `content` and no `extra_js`.
AISL_SHAPED_BASE = (
    "<!doctype html><html><head>"
    "<title>{% block title %}Site{% endblock %}</title>"
    '<meta name="description" content="{% block meta_description %}{% endblock %}">'
    "{% block page_head_metadata %}{% endblock %}"
    "</head><body><nav>chrome</nav>"
    "{% block body %}{% endblock %}"
    "{% block extra_scripts %}{% endblock %}"
    "</body></html>"
)

# Shaped like DataTalksClub/website's course_platform_templates/base.html: `content` and
# `extra_js`, robots under `meta_robots`, no `meta_description`, no `page_head_metadata`.
DTC_SHAPED_BASE = (
    "<!doctype html><html><head>"
    "<title>{% block title %}Site{% endblock %}</title>"
    "{% block meta_robots %}{% endblock %}"
    "</head><body><nav>chrome</nav>"
    "{% block content %}{% endblock %}"
    "{% block extra_js %}{% endblock %}"
    "</body></html>"
)

CONFORMING_BASE = (
    "<!doctype html><html><head>"
    "<title>{% block title %}Site{% endblock %}</title>"
    '<meta name="description" content="{% block meta_description %}{% endblock %}">'
    "{% block page_head_metadata %}{% endblock %}"
    "</head><body><nav>chrome</nav>"
    "{% block content %}{% endblock %}"
    "{% block extra_js %}{% endblock %}"
    "</body></html>"
)

# The AI-Shipping-Labs adapter this issue asks that site to add: three lines, once, for
# every shared public page.
AISL_SEAM_OVERRIDE = (
    '{% extends "base.html" %}\n'
    "{% block body %}{% block content %}{% endblock %}{% endblock %}\n"
    "{% block extra_scripts %}{% block extra_js %}{% endblock %}{% endblock %}\n"
)


def _site_dir(tmp_path, base_source=None, seam_source=None, shadowed=()):
    """Build a synthetic site template directory and return its path."""

    root = tmp_path / "templates"
    root.mkdir(parents=True, exist_ok=True)
    if base_source is not None:
        (root / "base.html").write_text(base_source)
    if seam_source is not None:
        seam = root / PUBLIC_BASE_TEMPLATE
        seam.parent.mkdir(parents=True, exist_ok=True)
        seam.write_text(seam_source)
    for name in shadowed:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{% extends "base.html" %}{% block body %}shadowed by the site{% endblock %}'
        )
    return root


def _templates_with(settings, site_dir, replace=False):
    engine = dict(settings.TEMPLATES[0])
    engine["DIRS"] = [str(site_dir)] if replace else [str(site_dir), *engine["DIRS"]]
    return [engine]


def _messages(settings, site_dir, replace=False):
    with override_settings(TEMPLATES=_templates_with(settings, site_dir, replace=replace)):
        return check_public_base_block_contract(app_configs=None)


def _ids(messages):
    return sorted(message.id for message in messages)


def _aisl_installed_apps():
    """The package apps AI-Shipping-Labs/website installs, as app configs."""

    from django.apps import apps as django_apps

    names = {
        "community_base.kernel",
        "community_base.config",
        "community_base.api",
        "community_base.studio",
        "community_base.jobs",
        "community_base.mail",
        "community_base.content_sync",
        "community_base.knowledge_base",
    }
    return [config for config in django_apps.get_app_configs() if config.name in names]


# ---------------------------------------------------------------------------
# A site that satisfies the contract sees no change at all.
# ---------------------------------------------------------------------------


def test_the_test_project_passes_the_check():
    """The package's own project satisfies the contract, so the check must be quiet in it."""

    assert check_public_base_block_contract(app_configs=None) == []


def test_a_conforming_site_passes_the_check(tmp_path, settings):
    assert _messages(settings, _site_dir(tmp_path, CONFORMING_BASE)) == []


@pytest.mark.parametrize("path", public_templates(), ids=lambda path: pathlib.Path(path).name)
def test_the_seam_changes_nothing_for_a_conforming_site(path, settings, tmp_path):
    """Every public template renders byte-identically through the seam and without it.

    This is the constraint stated as a measurement rather than an assertion: the shipped
    seam defines no blocks and emits nothing, so on a site whose base already names the
    contracted slots, introducing it changes no byte of any of the 41 pages. The direct
    comparison is built by taking the shipped template's own source and swapping only its
    `extends` target back to `base.html`.
    """

    site_dir = _site_dir(tmp_path, CONFORMING_BASE)
    source = pathlib.Path(path).read_text()
    direct_source = source.replace(
        f'{{% extends "{PUBLIC_BASE_TEMPLATE}" %}}', '{% extends "base.html" %}', 1
    )
    assert direct_source != source

    loader_name = "/".join(
        pathlib.Path(path).parts[pathlib.Path(path).parts.index("templates") + 1 :]
    )

    with override_settings(TEMPLATES=_templates_with(settings, site_dir)):
        engine = engines["django"]
        try:
            through_seam = render_to_string(loader_name, {})
        except Exception as error:  # noqa: BLE001 - compared against the direct render below
            through_seam = f"{type(error).__name__}"
        try:
            direct = engine.from_string(direct_source).render({})
        except Exception as error:  # noqa: BLE001 - compared against the seam render above
            direct = f"{type(error).__name__}"

    assert through_seam == direct


# ---------------------------------------------------------------------------
# A site whose base drops a contracted block is told which one, and where from.
# ---------------------------------------------------------------------------


def test_a_base_without_content_is_an_error_naming_the_block_and_a_template(tmp_path, settings):
    """Reproduces AI-Shipping-Labs/website: `body` instead of `content`."""

    messages = _messages(settings, _site_dir(tmp_path, AISL_SHAPED_BASE))

    errors = [message for message in messages if isinstance(message, Error)]
    assert len(errors) == 1
    error = errors[0]
    assert error.id == BLOCK_CHECK_ID["content"] == "community_base.kernel.E001"
    assert "'content'" in error.msg
    assert ".html" in error.msg
    assert "{% block content %}" in error.hint


def test_the_aisl_unsubscribe_page_is_named_by_the_check(tmp_path, settings):
    """The page this issue was opened about, reproduced as closely as a package test can.

    AI-Shipping-Labs/website installs the mail and knowledge-base apps of the five that
    ship public pages, shadows all three knowledge-base templates with its own copies, and
    its base names the body slot `body`. What is left is the two mail pages, one of which
    is the mounted public unsubscribe page that serves 21kB of chrome and no form today.
    """

    assert any(
        template_name == "community_base/mail/unsubscribe.html"
        for _, template_name, _ in PUBLIC_TEMPLATES
    )

    site_dir = _site_dir(
        tmp_path,
        AISL_SHAPED_BASE,
        shadowed=[
            "knowledge_base/docs_home.html",
            "knowledge_base/page_detail.html",
            "knowledge_base/wiki_home.html",
        ],
    )
    with override_settings(TEMPLATES=_templates_with(settings, site_dir)):
        messages = check_public_base_block_contract(app_configs=_aisl_installed_apps())
        html = render_to_string("community_base/mail/unsubscribe.html", {})

    error = next(message for message in messages if message.id == BLOCK_CHECK_ID["content"])
    assert "community_base/mail/unsubscribe.html" in error.msg
    assert "community_base/mail/click_notice.html" in error.msg
    # No knowledge-base template is named: those three are the site's own copies.
    assert "knowledge_base/" not in error.msg
    # The defect itself: full chrome, no body, HTTP 200, nothing in the logs.
    assert "<nav>chrome</nav>" in html
    assert "cb-page" not in html


def test_an_aisl_shaped_base_also_warns_about_extra_js(tmp_path, settings):
    messages = _messages(settings, _site_dir(tmp_path, AISL_SHAPED_BASE))

    warnings = [message for message in messages if isinstance(message, Warning)]
    assert _ids(warnings) == [BLOCK_CHECK_ID["extra_js"]]
    assert "'extra_js'" in warnings[0].msg


def test_a_dtc_shaped_base_warns_twice_and_does_not_error(tmp_path, settings):
    """Reproduces DataTalksClub/website: `content` is fine, the head blocks are not."""

    messages = _messages(settings, _site_dir(tmp_path, DTC_SHAPED_BASE))

    assert [message for message in messages if isinstance(message, Error)] == []
    assert _ids(messages) == sorted(
        [BLOCK_CHECK_ID["meta_description"], BLOCK_CHECK_ID["page_head_metadata"]]
    )
    assert all(isinstance(message, Warning) for message in messages)


def test_the_noindex_the_dtc_shape_drops_is_really_dropped(tmp_path, settings):
    """The warning is about a real loss, not a naming preference."""

    site_dir = _site_dir(tmp_path, DTC_SHAPED_BASE)
    with override_settings(TEMPLATES=_templates_with(settings, site_dir)):
        html = render_to_string("community_base/mail/unsubscribe.html", {})

    assert "noindex" not in html


# ---------------------------------------------------------------------------
# The seam override is the fix, and the check agrees that it is.
# ---------------------------------------------------------------------------


def test_the_seam_override_clears_the_error_and_renders_the_body(tmp_path, settings):
    site_dir = _site_dir(tmp_path, AISL_SHAPED_BASE, seam_source=AISL_SEAM_OVERRIDE)

    with override_settings(TEMPLATES=_templates_with(settings, site_dir)):
        messages = check_public_base_block_contract(app_configs=None)
        html = render_to_string("community_base/mail/unsubscribe.html", {})

    assert messages == []
    assert "<nav>chrome</nav>" in html
    assert "cb-page" in html


def test_the_seam_override_routes_extra_js_into_the_site_script_slot(tmp_path, settings):
    """`extra_js` is the block AI-Shipping-Labs calls `extra_scripts`."""

    without = _site_dir(tmp_path / "without", AISL_SHAPED_BASE)
    with override_settings(TEMPLATES=_templates_with(settings, without)):
        dropped = render_to_string("accounts/account.html", {})
    assert "cbApiForm" not in dropped

    mapped = _site_dir(tmp_path / "with", AISL_SHAPED_BASE, seam_source=AISL_SEAM_OVERRIDE)
    with override_settings(TEMPLATES=_templates_with(settings, mapped)):
        restored = render_to_string("accounts/account.html", {})
    assert "cbApiForm" in restored


# ---------------------------------------------------------------------------
# What the check refuses to complain about.
# ---------------------------------------------------------------------------


def test_a_template_the_site_has_shadowed_is_not_the_package_problem(tmp_path, settings):
    """A site's own copy at the same name fills the site's own blocks.

    AI-Shipping-Labs/website shadows all three package knowledge-base templates today, so
    without this the check would name blocks that no package template actually serves
    there.
    """

    extra_js_fillers = [
        template_name for _, template_name, blocks in PUBLIC_TEMPLATES if "extra_js" in blocks
    ]
    assert len(extra_js_fillers) == 3

    base_without_extra_js = CONFORMING_BASE.replace(
        "{% block extra_js %}{% endblock %}", "<!-- no script slot -->"
    )

    unshadowed = _messages(settings, _site_dir(tmp_path, base_without_extra_js))
    assert _ids(unshadowed) == [BLOCK_CHECK_ID["extra_js"]]

    shadowed = _messages(
        settings,
        _site_dir(tmp_path / "shadowed", base_without_extra_js, shadowed=extra_js_fillers),
    )
    assert shadowed == []


def test_an_app_that_is_not_installed_contributes_nothing(tmp_path, settings):
    """`app_configs` scopes the check, so a site is not told about pages it does not have."""

    base_without_extra_js = CONFORMING_BASE.replace(
        "{% block extra_js %}{% endblock %}", "<!-- no script slot -->"
    )
    site_dir = _site_dir(tmp_path, base_without_extra_js)

    from django.apps import apps as django_apps

    kernel_only = [django_apps.get_app_config("cb_kernel")]
    with override_settings(TEMPLATES=_templates_with(settings, site_dir)):
        assert check_public_base_block_contract(app_configs=kernel_only) == []


# ---------------------------------------------------------------------------
# A chain the check cannot read is a louder failure, reported as such.
# ---------------------------------------------------------------------------


def test_a_missing_template_in_the_chain_is_one_error_rather_than_five(tmp_path, settings):
    site_dir = _site_dir(tmp_path, '{% extends "no_such_layout.html" %}')

    messages = _messages(settings, site_dir)

    assert len(messages) == 1
    assert messages[0].id == "community_base.kernel.E002"
    assert "'no_such_layout.html' does not exist" in messages[0].msg


def test_a_base_extending_a_variable_is_reported_rather_than_guessed(tmp_path, settings):
    site_dir = _site_dir(tmp_path, "{% extends layout %}{% block content %}{% endblock %}")

    messages = _messages(settings, site_dir)

    assert len(messages) == 1
    assert messages[0].id == "community_base.kernel.E002"
    assert "named by a variable" in messages[0].msg


def test_a_base_that_does_not_compile_is_reported(tmp_path, settings):
    site_dir = _site_dir(tmp_path, "{% block content %}{% endblock_wrong %}")

    messages = _messages(settings, site_dir)

    assert len(messages) == 1
    assert messages[0].id == "community_base.kernel.E002"
    assert "does not compile" in messages[0].msg


# ---------------------------------------------------------------------------
# The Studio check is a different check about a different template.
# ---------------------------------------------------------------------------


def test_this_check_does_not_duplicate_the_studio_one():
    from community_base.studio.checks import CONTRACT_BLOCK_NAMES as studio_blocks
    from community_base.studio.checks import check_studio_content_block_contract

    assert check_public_base_block_contract is not check_studio_content_block_contract
    assert "studio_content" in studio_blocks
    assert "studio_content" not in BLOCK_CHECK_ID
    assert set(BLOCK_CHECK_ID).isdisjoint({"studio_content"})
