"""The icon library the shell loads: vendored, pinned, same-origin, and replaceable."""

import hashlib
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

from django.template import engines
from django.template.loader import render_to_string

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "community_base"
VENDOR_DIR = PACKAGE_ROOT / "studio" / "static" / "community_base" / "vendor"
LUCIDE = VENDOR_DIR / "lucide.min.js"
LUCIDE_VERSION = "1.47.0"
LUCIDE_SHA256 = "c3291ea757ff3da0fc45a41d3ff60d61da9b257314962c5cdded94ca0df05d7a"


def shell_request(route_name="studio_dashboard"):
    return SimpleNamespace(
        resolver_match=SimpleNamespace(url_name=route_name),
        user=SimpleNamespace(is_superuser=False),
        session={},
    )


def render_shell():
    return render_to_string("community_base/studio/base.html", {"request": shell_request()})


def render_child(body):
    template = engines["django"].from_string(
        '{% extends "community_base/studio/base.html" %}'
        "{% block studio_icon_script %}" + body + "{% endblock %}"
    )
    return template.render({"request": shell_request()})


def test_the_shell_loads_the_icon_library_from_the_packages_own_static_files():
    html = render_shell()

    assert '<script src="/static/community_base/vendor/lucide.min.js"></script>' in html


def test_the_vendored_icon_library_is_the_pinned_upstream_umd_build():
    source = LUCIDE.read_bytes()

    assert hashlib.sha256(source).hexdigest() == LUCIDE_SHA256
    assert f"lucide v{LUCIDE_VERSION}".encode() in source[:400]


def test_the_vendored_build_exposes_the_api_the_shell_calls():
    # community_base/studio.js calls `window.lucide.createIcons()` with no arguments, and the
    # markup names icons with `data-lucide`. A replacement build missing either is unusable.
    source = LUCIDE.read_text(encoding="utf-8")

    assert "createIcons" in source
    assert "data-lucide" in source
    assert "global.lucide" in source or "a.lucide" in source or ".lucide={}" in source


def test_the_vendored_file_records_where_it_came_from():
    note = (VENDOR_DIR / "README.txt").read_text(encoding="utf-8")

    assert LUCIDE_VERSION in note
    assert "registry.npmjs.org/lucide" in note
    assert LUCIDE_SHA256 in note
    assert (VENDOR_DIR / "lucide-LICENSE.txt").exists()


def tracked_package_files():
    """Every file git tracks under `community_base/`, so local build output is out of scope."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", "community_base"],
        cwd=PACKAGE_ROOT.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    return [PACKAGE_ROOT.parent / name for name in listing.stdout.split("\0") if name]


def test_no_third_party_script_host_is_left_anywhere_in_the_package():
    # `unpkg.com/lucide@latest` executed whatever unpkg served that day on a staff surface, and a
    # `script-src 'self'` site blocked it outright. Neither may come back by copy-paste.
    offenders = []
    for path in tracked_package_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if "unpkg" in line or re.search(r"@latest\b", line):
                where = path.relative_to(PACKAGE_ROOT.parent)
                offenders.append(f"{where}:{number}: {line.strip()}")

    assert offenders == []


def test_the_vendored_bundle_is_tracked_so_it_ships_in_the_wheel():
    tracked = {path.name for path in tracked_package_files()}

    assert "lucide.min.js" in tracked
    assert "lucide-LICENSE.txt" in tracked


def test_the_shell_serves_no_cross_origin_script_or_stylesheet():
    html = render_shell()

    assert 'src="http' not in html
    assert 'href="http' not in html


def test_a_site_that_ships_its_own_icon_library_can_replace_the_block():
    html = render_child('<script src="/static/site/icons.js"></script>')

    assert "/static/site/icons.js" in html
    assert "vendor/lucide.min.js" not in html


def test_the_icon_library_loads_in_head_before_extra_head_and_before_studio_js():
    template = engines["django"].from_string(
        '{% extends "community_base/studio/base.html" %}'
        '{% block extra_head %}<meta name="site-marker">{% endblock %}'
    )
    html = template.render({"request": shell_request()})

    assert html.index("vendor/lucide.min.js") < html.index('<meta name="site-marker">')
    assert html.index('<meta name="site-marker">') < html.index("</head>")
    # studio.js calls `window.lucide.createIcons()` as it runs, so the library must already
    # have executed by then.
    assert html.index("vendor/lucide.min.js") < html.index("community_base/studio.js")
