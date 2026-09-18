"""Every reference inside a shipped static file must resolve to a shipped file.

C7.20 vendored `lucide.min.js` and shipped it without the `lucide.min.js.map`
its own trailing `sourceMappingURL` names. Nothing in this package noticed: the
file was present in the wheel, the icons rendered, and the package suite was
green. It broke the first consumer to run `collectstatic` under manifest-based
static storage, which post-processes JavaScript and hard-fails on a reference it
cannot resolve, taking that site's deploy down.

The lesson this pins is that "the asset ships" and "what the asset points at
ships" are different claims, and only the first one was checked.
"""

import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "community_base"

# Both spellings WhiteNoise and the source-map convention accept.
_REFERENCE = re.compile(r"(?:sourceMappingURL|sourceURL)\s*=\s*(?P<target>[^\s*'\"]+)")


def _static_files() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in {".js", ".css"}
        and "static" in path.parts
        and "node_modules" not in path.parts
    )


def test_the_package_ships_at_least_one_static_file():
    # Guards the guard: an empty enumeration would make every assertion below
    # vacuous, which is how a check quietly stops checking.
    assert _static_files(), "found no shipped static files to check"


@pytest.mark.parametrize("path", _static_files(), ids=lambda p: p.name)
def test_shipped_static_file_references_only_shipped_files(path: Path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    for match in _REFERENCE.finditer(text):
        target = match.group("target").strip()
        if target.startswith(("data:", "http://", "https://", "//")):
            continue
        resolved = (path.parent / target).resolve()
        assert resolved.is_file(), (
            f"{path.relative_to(PACKAGE_ROOT)} references {target!r}, "
            f"which this package does not ship. A consumer running "
            f"collectstatic under manifest static storage fails on this. "
            f"Ship the file, or strip the reference."
        )
