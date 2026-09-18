"""The public template contract, pinned over the package tree.

`docs/02-architecture.md` section 5 names this file as the guard that shared public
templates keep to the contract a consuming site can satisfy. It did not exist, so the
contract was unmeasured while the package grew to 41 public templates
(`docs/plan/evidence/adoption-assumption-audit-2026-09-18.md`).

What the contract is worth is bounded, and the bound is the point. These assertions say
the package emits only the block names and only the class hooks it promised. They cannot
say a consuming site's `base.html` DEFINES those block names: a block a site's base does
not define is dropped by Django with no error, and both adopting sites drop a different
part of the five. That half is the site's, and the audit records it.
"""

import re

from tests.template_tree import (
    CONTRACT_BLOCK_NAMES,
    PACKAGE_ROOT,
    block_names,
    class_names,
    public_templates,
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
