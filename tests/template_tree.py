"""Read the package template tree as text, for contract assertions.

Parsing the files rather than rendering them is deliberate: the contract is about what the
package EMITS, which has to hold for every consuming site, including one whose `base.html`
defines a different set of block names and whose settings this suite never loads.
"""

import pathlib
import re

from community_base.kernel.template_contract import (
    CONTRACT_BLOCK_NAMES,
    PUBLIC_BASE_TEMPLATE,
    SITE_BASE_TEMPLATE,
)

__all__ = [
    "CONTRACT_BLOCK_NAMES",
    "PACKAGE_ROOT",
    "PUBLIC_BASE_SOURCE_PATH",
    "block_names",
    "class_names",
    "extends_target",
    "public_templates",
]

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "community_base"

# The one package template that is allowed to extend the site's own `base.html`: the seam
# every shared public template goes through instead.
PUBLIC_BASE_SOURCE_PATH = PACKAGE_ROOT / "kernel" / "templates" / PUBLIC_BASE_TEMPLATE

_TEMPLATE_SYNTAX_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)
_BLOCK_RE = re.compile(r"\{%\s*block\s+([A-Za-z0-9_]+)")
_CLASS_RE = re.compile(r'class="([^"]*)"')
_EXTENDS_RE = re.compile(r'\{%\s*extends\s+"([^"]+)"\s*%\}')


def extends_target(path: pathlib.Path) -> str | None:
    """The template this one extends, when it is named by a literal string."""

    match = _EXTENDS_RE.search(path.read_text())
    return match.group(1) if match else None


def public_templates() -> list[pathlib.Path]:
    """Every shared public page template: the ones that go through the public base seam."""

    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.html")
        if extends_target(path) == PUBLIC_BASE_TEMPLATE
    )


def templates_extending_the_site_base() -> list[pathlib.Path]:
    """Every package template that reaches for the site's own `base.html` directly."""

    return sorted(
        path for path in PACKAGE_ROOT.rglob("*.html") if extends_target(path) == SITE_BASE_TEMPLATE
    )


def block_names(path: pathlib.Path) -> set[str]:
    return set(_BLOCK_RE.findall(path.read_text()))


def class_names(path: pathlib.Path) -> set[str]:
    """Class names in a template, with template syntax removed first.

    A class attribute may hold a conditional, and the words of that conditional are not
    class names.
    """

    names: set[str] = set()
    for attribute in _CLASS_RE.findall(path.read_text()):
        names.update(_TEMPLATE_SYNTAX_RE.sub(" ", attribute).split())
    return names
