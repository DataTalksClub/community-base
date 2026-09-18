"""The public template contract, pinned over the package tree.

`docs/02-architecture.md` section 5 names this file as the guard that shared public
templates keep to the contract a consuming site can satisfy. It did not exist, so the
contract was unmeasured while the package grew to 41 public templates
(`docs/plan/evidence/adoption-assumption-audit-2026-09-18.md`).

What the contract is worth is bounded, and the bound is the point. These assertions say
the package emits only the block names and only the class hooks it promised, and that it
reaches the site's own chrome through exactly one seam. Whether a particular site's chain
DEFINES those block names is not a question a package test can answer -- it depends on
settings this suite never loads -- and it is the question
`community_base.kernel.checks.check_public_base_block_contract` answers at
`manage.py check` time in the site, with `tests/test_public_base_contract.py` exercising it
against two synthetic bases shaped like the two real ones.
"""

import re

from community_base.kernel.template_contract import (
    PUBLIC_BASE_TEMPLATE,
    PUBLIC_TEMPLATES,
    SITE_BASE_TEMPLATE,
)
from tests.template_tree import (
    CONTRACT_BLOCK_NAMES,
    PACKAGE_ROOT,
    PUBLIC_BASE_SOURCE_PATH,
    block_names,
    class_names,
    extends_target,
    public_templates,
    templates_extending_the_site_base,
)


def test_public_templates_exist():
    """The scan is worthless if it silently matches nothing."""

    assert len(public_templates()) > 30


def test_public_templates_use_only_contracted_blocks():
    """A block a site's base.html never defines renders as nothing, with no error."""

    offenders = {
        path.as_posix(): sorted(block_names(path) - set(CONTRACT_BLOCK_NAMES))
        for path in public_templates()
        if block_names(path) - set(CONTRACT_BLOCK_NAMES)
    }
    assert offenders == {}


def test_public_templates_fill_the_content_block():
    """The body of a public page lives in `content` and nowhere else."""

    missing = [path.as_posix() for path in public_templates() if "content" not in block_names(path)]
    assert missing == []


def test_public_templates_use_only_cb_class_hooks():
    """A site styles `cb-` hooks; a utility class from one site's stylesheet is unstyled
    on the other."""

    offenders = {}
    for path in public_templates():
        foreign = sorted(name for name in class_names(path) if not name.startswith("cb-"))
        if foreign:
            offenders[path.as_posix()] = foreign
    assert offenders == {}


def test_public_templates_carry_no_inline_style():
    """A site with a `style-src 'self'` policy blocks an inline style outright.

    Inline SCRIPT is deliberately not asserted here: two public templates carry one, and
    both adopting sites allow `'unsafe-inline'` for scripts today. The audit records them
    rather than this test pinning a stricter rule than the package keeps.
    """

    offenders = [path.as_posix() for path in public_templates() if "<style" in path.read_text()]
    assert offenders == []


def test_every_static_reference_resolves_to_a_shipped_file():
    """A site running `ManifestStaticFilesStorage` raises on a `{% static %}` miss.

    One adopting site runs plain storage in development and only manifests in production,
    the other manifests everywhere including local development, so a missing package asset
    is a hard error on one site and invisible on the other. This walks the whole package
    template tree, not only the public templates.
    """

    shipped = {
        path.relative_to(static_dir).as_posix()
        for static_dir in PACKAGE_ROOT.rglob("static")
        if static_dir.is_dir()
        for path in static_dir.rglob("*")
        if path.is_file()
    }
    missing = {}
    for path in PACKAGE_ROOT.rglob("*.html"):
        referenced = set(re.findall(r"\{%\s*static\s+['\"]([^'\"]+)['\"]", path.read_text()))
        absent = sorted(referenced - shipped)
        if absent:
            missing[path.as_posix()] = absent
    assert missing == {}


def test_public_templates_reference_no_external_host():
    """A third-party CDN is unreachable under a site content security policy."""

    offenders = {}
    for path in public_templates():
        hosts = sorted(set(re.findall(r'(?:src|href)="(https?://[^/"]+)', path.read_text())))
        if hosts:
            offenders[path.as_posix()] = hosts
    assert offenders == {}


def test_only_the_seam_extends_the_site_base():
    """One package template may name the site's own `base.html`, and it is the seam.

    Every other public template extends the seam instead, so a site whose chrome names
    these slots differently has one file to override rather than forty-one to fork. That is
    not theoretical: AI-Shipping-Labs/website forked all three package knowledge-base
    templates to rename `content` to `body`, which is what the seam exists to stop.
    """

    assert [path.as_posix() for path in templates_extending_the_site_base()] == [
        PUBLIC_BASE_SOURCE_PATH.as_posix()
    ]


def test_the_seam_is_a_pass_through():
    """The shipped seam adds nothing, so a site that already satisfies the contract sees
    no change from its introduction.

    A seam that defined blocks of its own would change what a conforming site renders. This
    one extends `base.html` and stops; everything else in the file is a comment, which
    Django emits as nothing.
    """

    source = PUBLIC_BASE_SOURCE_PATH.read_text()
    assert extends_target(PUBLIC_BASE_SOURCE_PATH) == SITE_BASE_TEMPLATE
    assert block_names(PUBLIC_BASE_SOURCE_PATH) == set()
    assert source.splitlines()[0] == f'{{% extends "{SITE_BASE_TEMPLATE}" %}}'


def test_generated_contract_matches_the_template_tree():
    """`community_base/kernel/template_contract.py` is data the check reads; it must not
    drift from the templates it describes."""

    measured = []
    for path in public_templates():
        parts = path.relative_to(PACKAGE_ROOT.parent).parts
        index = parts.index("templates")
        measured.append(
            (
                ".".join(parts[:index]),
                "/".join(parts[index + 1 :]),
                tuple(sorted(block_names(path))),
            )
        )
    measured_rows = tuple(measured)
    if measured_rows != PUBLIC_TEMPLATES:
        regenerated = "\n".join(f"    {row!r}," for row in measured_rows)
        raise AssertionError(
            "PUBLIC_TEMPLATES in community_base/kernel/template_contract.py no longer "
            "matches the template tree. Replace it with:\n" + regenerated
        )


def test_every_contracted_template_resolves_under_its_app():
    """The loader names in the contract data are the names the loader actually uses.

    The check resolves each of these through the real template loader to decide whether a
    site has shadowed it. A name that no longer resolves would make the check skip a
    template silently, which is the same class of quiet no-op the contract exists to stop.
    """

    missing = [
        (app_name, template_name)
        for app_name, template_name, _ in PUBLIC_TEMPLATES
        if not (
            PACKAGE_ROOT.parent / app_name.replace(".", "/") / "templates" / template_name
        ).exists()
    ]
    assert missing == []


def test_the_seam_name_is_not_a_site_owned_path():
    """The seam lives under `community_base/`, so a site override of it is deliberate."""

    assert PUBLIC_BASE_TEMPLATE.startswith("community_base/")
