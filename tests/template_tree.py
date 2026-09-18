"""Read the package template tree as text, for contract assertions.

Parsing the files rather than rendering them is deliberate: the contract is about what the
package EMITS, which has to hold for every consuming site, including one whose `base.html`
defines a different set of block names and whose settings this suite never loads.
"""

import pathlib
import re

CONTRACT_BLOCK_NAMES = ("title", "meta_description", "page_head_metadata", "content", "extra_js")

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent / "community_base"

_TEMPLATE_SYNTAX_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)
_BLOCK_RE = re.compile(r"\{%\s*block\s+([A-Za-z0-9_]+)")
_CLASS_RE = re.compile(r'class="([^"]*)"')


def public_templates() -> list[pathlib.Path]:
    """Every package template that extends the consuming site's own base template."""

    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.html")
        if '{% extends "base.html" %}' in path.read_text()
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
