"""What the shared renderer must keep producing for the two apps that use it.

`community_base.knowledge_base` publishes live pages and
`community_base.curriculum` publishes unit bodies, so C7.8 may widen what the one
renderer accepts but may not change what these bodies produce. Every expectation
below was measured against the pre-C7.8 `knowledge_base.rendering.render_markdown`
and pinned here. The heading cases carry the one deliberate addition: headings now
carry the ids of section 4.1, which the knowledge base's table of contents and
DataTalks.Club's pinned fragments both need.
"""

import re

import pytest

from community_base.curriculum.rendering import render_annotated_markdown, render_markdown

# (markdown, html the renderer produced before C7.8 and must still produce)
UNCHANGED = [
    (
        "table",
        "| a | b |\n|---|---|\n| 1 | 2 |\n",
        "<table>\n<thead>\n<tr>\n<th>a</th>\n<th>b</th>\n</tr>\n</thead>\n<tbody>\n"
        "<tr>\n<td>1</td>\n<td>2</td>\n</tr>\n</tbody>\n</table>",
    ),
    (
        "fenced code",
        "```python\nprint(1)\n```\n",
        '<pre><code class="language-python">print(1)\n</code></pre>',
    ),
    ("a script is removed", "<script>alert(1)</script>\n\nhello\n", "\n\n<p>hello</p>"),
    (
        "links",
        "[a](https://example.com) [b](mailto:x@example.com) [c](javascript:alert(1))\n",
        '<p><a href="https://example.com">a</a> <a href="mailto:x@example.com">b</a> <a>c</a></p>',
    ),
    (
        "emphasis and inline code",
        "**bold** _em_ `code` ~~strike~~\n",
        "<p><strong>bold</strong> <em>em</em> <code>code</code> ~~strike~~</p>",
    ),
    (
        "lists",
        "- one\n- two\n    - nested\n\n1. first\n2. second\n",
        "<ul>\n<li>one</li>\n<li>two<ul>\n<li>nested</li>\n</ul>\n</li>\n</ul>\n"
        "<ol>\n<li>first</li>\n<li>second</li>\n</ol>",
    ),
    (
        "blockquote",
        "> quoted\n>\n> more\n",
        "<blockquote>\n<p>quoted</p>\n<p>more</p>\n</blockquote>",
    ),
    (
        "image sources",
        "![rel](images/d.png)\n\n![abs](/a/b.png)\n\n![cdn](https://cdn.example.com/x.png)\n",
        '<p><img alt="rel"></p>\n<p><img alt="abs" src="/a/b.png"></p>\n'
        '<p><img alt="cdn" src="https://cdn.example.com/x.png"></p>',
    ),
    (
        "raw html the allowlist keeps",
        '<figure><img src="/a/b.png" alt="x"><figcaption>cap</figcaption></figure>\n',
        '<figure><img src="/a/b.png" alt="x"><figcaption>cap</figcaption></figure>',
    ),
]

# (markdown, html before C7.8, html now) - the addition is the heading id and
# nothing else.
HEADING_IDS_ADDED = [
    (
        "repeated headings",
        "# Title\n\n## Setup\n\ntext\n\n## Setup\n\nmore\n\n## Setup\n\nend\n",
        "<h1>Title</h1>\n<h2>Setup</h2>\n<p>text</p>\n<h2>Setup</h2>\n<p>more</p>\n"
        "<h2>Setup</h2>\n<p>end</p>",
        '<h1 id="title">Title</h1>\n<h2 id="setup">Setup</h2>\n<p>text</p>\n'
        '<h2 id="setup-1">Setup</h2>\n<p>more</p>\n<h2 id="setup-2">Setup</h2>\n<p>end</p>',
    ),
    (
        "a heading with an entity",
        "## Café & Co\n\nx\n",
        "<h2>Café &amp; Co</h2>\n<p>x</p>",
        '<h2 id="cafe-co">Café &amp; Co</h2>\n<p>x</p>',
    ),
    (
        "a heading with no ascii letters",
        "## Привет\n\nx\n",
        "<h2>Привет</h2>\n<p>x</p>",
        '<h2 id="section">Привет</h2>\n<p>x</p>',
    ),
]

ANNOTATED_BODY = """Intro paragraph.

```python
value = compute()
```
<!--
structured: true
code_annotations:
  - line: 1
    text: Compute it.
-->

Outro.
"""


@pytest.mark.parametrize(
    ("body", "expected"),
    [(body, expected) for _, body, expected in UNCHANGED],
    ids=[name for name, *_ in UNCHANGED],
)
def test_the_shared_renderer_produces_what_the_app_renderers_produced(body, expected):
    assert render_markdown(body) == expected


@pytest.mark.parametrize(
    ("body", "before", "now"),
    [(body, before, now) for _, body, before, now in HEADING_IDS_ADDED],
    ids=[name for name, *_ in HEADING_IDS_ADDED],
)
def test_headings_gained_ids_and_nothing_else(body, before, now):
    rendered = render_markdown(body)

    assert rendered == now
    assert _without_heading_ids(rendered) == before


def test_code_annotations_render_exactly_as_they_did():
    """C5.1g's markup is generated after sanitizing and is unchanged by C7.8."""

    assert render_annotated_markdown(ANNOTATED_BODY) == (
        "<p>Intro paragraph.</p>\n"
        '<div class="annotated-code-block"><pre>'
        '<span class="code-line-gutter" aria-hidden="true">'
        '<span class="code-line-number">1</span></span><code class="language-python">'
        '<span class="code-annotation-line is-highlighted" data-line-number="1">value = c'
        "ompute()</span></code></pre></div>"
        '<aside class="code-annotations" aria-labelledby="code-annotations-1" data-testid'
        '="code-annotations">'
        '<h3 id="code-annotations-1" class="code-annotations-heading">Code annotations</h'
        '3><ol class="code-annotation-list">'
        '<li class="code-annotation-note" data-testid="code-annotation-note">'
        '<span class="code-annotation-label">Line 1:</span>'
        '<span class="code-annotation-text">Compute it.</span></li></ol></aside>\n'
        "<p>Outro.</p>"
    )


def _without_heading_ids(rendered: str) -> str:
    return re.sub(r'<h([1-6]) id="[^"]*">', r"<h\1>", rendered)
