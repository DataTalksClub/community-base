from __future__ import annotations

from pathlib import Path

import pytest

from community_base.content_sync.convert.documents import PROFILES, convert_documents
from community_base.content_sync.convert.report import read_front_matter

PROFILE = PROFILES["dtc-articles"]
FROZEN_PAIR_FIXTURE = (
    Path(__file__).parent / "dtc_article_fixtures/practical-guide-better-code.source"
)
FROZEN_PAIR_SHA = "cbb77e4c9b0bc6ce153b80899a11b590d51687872065e99583f8ca1f9ab60e5e"


def write_raw_article(root: Path, body: str) -> tuple[Path, bytes]:
    path = root / "articles/2024/24-01-02-raw.md"
    path.parent.mkdir(parents=True)
    front = "title: Raw\ndescription: Code\ndate: 2024-01-02\n"
    raw = f"---\n{front}---\n{body}".encode()
    path.write_bytes(raw)
    return path, raw


def converted_body(root: Path) -> str:
    text = (root / "articles/raw/index.md").read_text(newline="")
    _, body = read_front_matter(text)
    return body


def raw_pair_interiors(text: str) -> list[str]:
    found = []
    remaining = text
    while "{% raw %}" in remaining:
        _, remaining = remaining.split("{% raw %}", 1)
        interior, remaining = remaining.split("{% endraw %}", 1)
        found.append(interior.removeprefix("\n"))
    return found


def test_both_frozen_public_raw_pairs_preserve_their_code(tmp_path):
    raw = FROZEN_PAIR_FIXTURE.read_bytes()
    source = tmp_path / "articles/2020/20-12-07-practical-guide-better-code.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(raw)
    pairs = raw_pair_interiors(raw.decode())
    report = convert_documents(tmp_path, PROFILE)
    target = tmp_path / "articles/practical-guide-better-code/index.md"
    metadata, output_body = read_front_matter(target.read_text())
    assert report.ok and len(pairs) == 2
    assert all(pair in output_body for pair in pairs)
    assert "{% raw %}" not in output_body and "{% endraw %}" not in output_body
    assert metadata["extra"]["dtc_article_v1"]["source"]["sha256"] == FROZEN_PAIR_SHA


def test_two_raw_pairs_remove_only_wrappers_and_preserve_fenced_bytes(tmp_path):
    first = (
        "\n```yaml\nname: CI\nvalue: ${{ matrix.python-version }}\nliteral: '{% endraw %}'\n```\n\n"
    )
    second = "~~~python\r\nprint('café')\r\n{{ literal }}\r\n~~~~\r\n"
    body = (
        f"Before.\n{{% raw %}}{first}{{% endraw %}}\nBetween.\r\n"
        f"{{% raw %}}\r\n{second}{{% endraw %}}\r\nAfter.\n"
    )
    write_raw_article(tmp_path, body)
    report = convert_documents(tmp_path, PROFILE)
    result = converted_body(tmp_path)
    assert report.ok and report.verify() == []
    assert result == f"Before.\n{first.removeprefix(chr(10))}Between.\r\n{second}After.\n"
    assert result.count("${{ matrix.python-version }}") == 1
    assert "literal: '{% endraw %}'" in result


def test_wrapper_looking_lines_inside_an_existing_fence_are_literal(tmp_path):
    body = "```text\n{% raw %}\nliteral\n{% endraw %}\n```\n"
    write_raw_article(tmp_path, body)
    report = convert_documents(tmp_path, PROFILE)
    assert report.ok
    assert converted_body(tmp_path) == body


@pytest.mark.parametrize(
    "body",
    [
        "{% endraw %}\n",
        "{% raw %}\n```text\ncode\n```\n",
        "{% raw %}\nprose\n```text\ncode\n```\n{% endraw %}\n",
        "{% raw %}\n```text\ncode\n```\nprose\n{% endraw %}\n",
        "{% raw %}\n```text\ncode\n```\n```text\nsecond\n```\n{% endraw %}\n",
        "{% raw %}\n{% raw %}\n```text\ncode\n```\n{% endraw %}\n{% endraw %}\n",
        "{% raw %}\n```text\ncode\n``\n{% endraw %}\n",
        "{% raw %}\n```text\ncode\n~~~\n{% endraw %}\n",
        "{% raw %}\n```text\ncode\n",
        "{% raw extra %}\n```text\ncode\n```\n{% endraw %}\n",
        "{% raw\n```text\ncode\n```\n{% endraw %}\n",
        "{% endraw\n",
        "{% raw %} trailing\n```text\ncode\n```\n{% endraw %}\n",
        "{% include unknown.html %}\n",
        "{% raw %}\n<script>alert(1)</script>\n{% endraw %}\n",
    ],
    ids=[
        "stray-end",
        "missing-end",
        "prose-before",
        "prose-after",
        "multiple-fences",
        "nested",
        "short-close",
        "mismatched-close",
        "unclosed-fence",
        "malformed-open",
        "unterminated-open-token",
        "unterminated-end-token",
        "open-with-prose",
        "unknown-include",
        "raw-script-prose",
    ],
)
def test_raw_grammar_refuses_unsafe_or_malformed_bodies(tmp_path, body):
    path, raw = write_raw_article(tmp_path, body)
    report = convert_documents(tmp_path, PROFILE)
    assert not report.ok and len(report.refusals) == 1
    assert report.refusals[0].rule == "4.1"
    assert path.read_bytes() == raw
    assert not (tmp_path / "articles/raw/index.md").exists()


def test_raw_fence_keeps_a_youtube_include_as_code(tmp_path):
    body = (
        "{% raw %}\n```liquid\n"
        '{% include youtube.html video_id="must-stay-code" %}\n'
        "```\n{% endraw %}\n"
    )
    write_raw_article(tmp_path, body)
    report = convert_documents(tmp_path, PROFILE)
    assert report.ok
    assert converted_body(tmp_path) == (
        '```liquid\n{% include youtube.html video_id="must-stay-code" %}\n```\n'
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            '{% include youtube.html video_id="outside" %}\nAfter prose.\n',
            "```embed\ntype: youtube\nid: outside\n```\nAfter prose.\n",
        ),
        (
            '{% include youtube.html video_id="outside" %}\r\n\r\nAfter prose.\r\n',
            "```embed\r\ntype: youtube\r\nid: outside\r\n```\r\n\r\nAfter prose.\r\n",
        ),
        (
            '{% include youtube.html video_id="outside" %}',
            "```embed\ntype: youtube\nid: outside\n```",
        ),
    ],
    ids=["lf-prose", "crlf-blank-and-prose", "terminal-without-line-end"],
)
def test_supported_youtube_include_preserves_its_line_boundary(tmp_path, body, expected):
    write_raw_article(tmp_path, body)
    report = convert_documents(tmp_path, PROFILE)
    assert report.ok and report.verify() == []
    assert converted_body(tmp_path) == expected
