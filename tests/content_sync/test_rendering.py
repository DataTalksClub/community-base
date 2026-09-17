"""The one dialect, the one sanitizer and the kept heading-id algorithm.

`FORMAT.md` section 4 is what these tests hold the renderer to. The heading-id
cases are the load-bearing ones: DataTalks.Club's pinned fragment contracts only
keep resolving while the suffixes count repeats from zero.
"""

from pathlib import Path

import pytest
from django.test import override_settings

from community_base.content_sync import rendering
from community_base.content_sync.check import check_repository, heading_ids
from community_base.content_sync.rendering import (
    PACKAGE_MARKDOWN_EXTENSIONS,
    HeadingIdAssigner,
    heading_slug,
    inject_heading_ids,
    markdown_extensions,
    plain_text,
    render_document,
    render_markdown,
    sanitize_rendered_html,
)

# --- the heading-id algorithm, section 4.1 -----------------------------------


def test_three_identical_headings_count_repeats_from_zero():
    """The donor rule: `setup`, `setup-1`, `setup-2`, never `setup-2`, `setup-3`.

    Copied from `content/docs_projection.py:_heading_ids` rather than imported,
    because the package must keep the algorithm after the donor is gone.
    """

    body = "## Setup\n\none\n\n## Setup\n\ntwo\n\n## Setup\n\nthree\n"

    rendered, headings = inject_heading_ids(
        "<h2>Setup</h2>\n<p>one</p>\n<h2>Setup</h2>\n<p>two</p>\n<h2>Setup</h2>\n<p>three</p>"
    )

    assert [heading["id"] for heading in headings] == ["setup", "setup-1", "setup-2"]
    assert '<h2 id="setup">Setup</h2>' in rendered
    assert '<h2 id="setup-1">Setup</h2>' in rendered
    assert '<h2 id="setup-2">Setup</h2>' in rendered
    # The same three ids come out of the whole pipeline and out of the validator.
    assert [heading["id"] for heading in render_document(body).headings] == [
        "setup",
        "setup-1",
        "setup-2",
    ]
    assert [identifier for _, identifier, _ in heading_ids(body)] == [
        "setup",
        "setup-1",
        "setup-2",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Setup", "setup"),
        ("A/B Testing", "a-b-testing"),
        ("What's new?!", "what-s-new"),
        ("  Trailing  ", "trailing"),
        ("Café & Co", "cafe-co"),
        ("Привет", "section"),
        ("!!!", "section"),
        ("", "section"),
    ],
)
def test_the_slug_is_nfkd_ascii_lowercase_with_an_empty_result_becoming_section(text, expected):
    assert heading_slug(text) == expected


def test_the_assigner_is_the_one_counter_the_validator_and_the_renderer_share():
    assigner = HeadingIdAssigner()

    assert [assigner.assign(text) for text in ("Setup", "Other", "Setup", "Setup")] == [
        "setup",
        "other",
        "setup-1",
        "setup-2",
    ]


def test_check_no_longer_carries_a_private_copy_of_the_algorithm():
    """C7.7 left the copy for C7.8 to remove; `check.py` now calls the shared one."""

    from community_base.content_sync import check

    assert not hasattr(check, "_heading_slug")
    assert check.HeadingIdAssigner is HeadingIdAssigner


def test_the_heading_title_is_the_visible_text_of_a_rendered_heading():
    _, headings = inject_heading_ids("<h3>A <code>fast</code> path &amp; more</h3>")

    assert headings == ({"level": 3, "id": "a-fast-path-more", "title": "A fast path & more"},)


def test_a_heading_that_already_carries_attributes_keeps_its_own_id():
    rendered, headings = inject_heading_ids('<h2 id="pinned">Setup</h2>\n<h2>Setup</h2>')

    assert '<h2 id="pinned">Setup</h2>' in rendered
    assert [heading["id"] for heading in headings] == ["setup"]


def test_injected_heading_ids_survive_the_sanitizer():
    assert 'id="setup"' in sanitize_rendered_html('<h2 id="setup">Setup</h2>')
    assert 'id="setup"' in render_markdown("## Setup\n")


# --- the dialect, section 4.1 ------------------------------------------------


def test_the_package_extension_set_is_the_documented_one():
    assert PACKAGE_MARKDOWN_EXTENSIONS == ("fenced_code", "tables", "sane_lists")
    assert "attr_list" not in PACKAGE_MARKDOWN_EXTENSIONS
    assert "md_in_html" not in PACKAGE_MARKDOWN_EXTENSIONS


def test_tables_fenced_code_and_sane_lists_are_on():
    rendered = render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in rendered and "<td>1</td>" in rendered

    rendered = render_markdown("```python\nprint(1)\n```\n")
    assert '<code class="language-python">' in rendered

    rendered = render_markdown("1. one\n\n- bullet\n")
    assert "<ol>" in rendered and "<ul>" in rendered


def test_attr_list_is_off_so_a_kramdown_attribute_list_is_inert_text():
    rendered = render_markdown("A paragraph.\n{: .fs-9 }\n")

    assert "fs-9" in rendered
    assert 'class="fs-9"' not in rendered


def test_a_liquid_tag_and_an_attribute_list_are_errors_and_a_script_is_removed(tmp_path):
    """The issue's second verification: two rejected by the validator, one stripped."""

    (tmp_path / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\n"
    )
    (tmp_path / "wiki").mkdir()
    body = "{% include youtube.html id='x' %}\n\nA line.\n{: .fs-9 }\n\n<script>alert(1)</script>\n"
    (tmp_path / "wiki" / "a-page.md").write_text(
        '---\ncontent_id: "88888888-8888-4888-8888-888888888888"\ntitle: A Page\n---\n\n' + body
    )

    diagnostics = check_repository(tmp_path)
    errors = [diagnostic.message for diagnostic in diagnostics if diagnostic.severity == "error"]

    assert any("Liquid is not part of the dialect" in message for message in errors)
    assert any("kramdown attribute lists" in message for message in errors)
    assert "<script>" not in render_markdown(body)
    assert "alert(1)" not in render_markdown(body)


def test_raw_html_the_dialect_keeps_and_raw_html_it_removes():
    rendered = render_markdown(
        '<figure><img src="/a/b.png" alt="x"><figcaption>cap</figcaption></figure>\n'
    )
    assert "<figure>" in rendered and "<figcaption>" in rendered

    rendered = render_markdown("<details><summary>s</summary>\n\nbody\n\n</details>\n")
    assert "<details>" in rendered and "<summary>" in rendered

    for snippet in (
        "<iframe src='/x'></iframe>",
        "<style>p{color:red}</style>",
        "<script>x</script>",
    ):
        rendered = render_markdown(snippet)
        assert "<iframe" not in rendered
        assert "<style" not in rendered
        assert "<script" not in rendered


def test_a_leading_h1_equal_to_the_title_is_stripped_by_the_renderer():
    document = render_document("# Guide\n\nBody.\n", "Guide")

    assert "<h1" not in document.html
    assert "<p>Body.</p>" in document.html
    assert "<h1" in render_document("# Other\n\nBody.\n", "Guide").html


# --- the mermaid and embed fences, section 4.1 -------------------------------


def test_a_mermaid_fence_escapes_its_source_into_a_pre():
    rendered = render_markdown("```mermaid\ngraph TD;\n  A-->B;\n```\n")

    assert rendered == '<pre class="mermaid">graph TD;\n  A--&gt;B;</pre>'
    assert sanitize_rendered_html(rendered) == rendered


@pytest.mark.parametrize(
    ("body", "expected_type", "expected_url"),
    [
        (
            "type: youtube\nid: dQw4w9WgXcQ",
            "youtube",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "type: loom\nid: 0a1b2c3d",
            "loom",
            "https://www.loom.com/share/0a1b2c3d",
        ),
    ],
)
def test_an_embed_fence_renders_hooks_and_a_plain_link_and_never_an_iframe(
    body, expected_type, expected_url
):
    rendered = render_markdown(f"```embed\n{body}\n```\n")

    assert f'data-embed-type="{expected_type}"' in rendered
    assert 'class="cb-embed"' in rendered
    assert f'<a href="{expected_url}">{expected_url}</a>' in rendered
    assert "<iframe" not in rendered
    assert sanitize_rendered_html(rendered) == rendered


@pytest.mark.parametrize(
    "body",
    [
        "type: vimeo\nid: 1",
        "type: youtube",
        "type: youtube\nid: a b\n",
        "type: youtube\nid: x\nautoplay: true",
        "- not a mapping",
    ],
)
def test_an_invalid_embed_body_stays_a_code_block_rather_than_losing_content(body):
    rendered = render_markdown(f"```embed\n{body}\n```\n")

    assert "cb-embed" not in rendered
    assert "<pre><code" in rendered


def test_a_mermaid_fence_shown_inside_a_longer_fence_is_not_drawn():
    rendered = render_markdown("````markdown\n```mermaid\ngraph TD;\n```\n````\n")

    assert "<pre><code" in rendered
    assert 'class="mermaid"' not in rendered


# --- the extension hook, section 4.2 -----------------------------------------


def test_the_package_extension_list_is_the_default():
    assert markdown_extensions()[:3] == list(PACKAGE_MARKDOWN_EXTENSIONS)
    assert len(markdown_extensions()) == 4


@override_settings(COMMUNITY_BASE={"MARKDOWN_EXTENSIONS": ["markdown.extensions.attr_list"]})
def test_a_site_appends_an_extension_and_its_output_still_passes_the_sanitizer():
    extensions = markdown_extensions()
    assert extensions[:3] == list(PACKAGE_MARKDOWN_EXTENSIONS)
    assert extensions[-1] == "markdown.extensions.attr_list"

    rendered = render_markdown('A paragraph.\n{: .fs-9 style="color:red" }\n')

    assert 'class="fs-9"' in rendered
    assert "color:red" not in rendered


# --- the sanitizer, section 4.2 ----------------------------------------------


def test_class_id_lang_and_title_survive_the_sanitizer():
    """C7.4's fix, pinned: nh3 asks the filter only about what its map admits."""

    html = sanitize_rendered_html('<p class="a" id="b" lang="en" title="t">x</p>')

    assert 'class="a"' in html and 'id="b"' in html
    assert 'lang="en"' in html and 'title="t"' in html


def test_the_embed_and_theme_figure_attributes_are_admitted():
    html = sanitize_rendered_html(
        '<div class="cb-embed" data-embed-type="youtube" data-embed-id="x">y</div>'
        '<img src="/a/b.png" alt="" data-theme-figure="dark">'
    )

    assert 'data-embed-type="youtube"' in html
    assert 'data-embed-id="x"' in html
    assert 'data-theme-figure="dark"' in html


def test_style_event_handlers_and_unknown_data_attributes_are_removed():
    html = sanitize_rendered_html('<p style="color:red" data-x="1" onmouseover="e()">x</p>')

    assert html == "<p>x</p>"


def test_only_the_donor_url_schemes_are_admitted():
    assert 'href="https://example.com"' in sanitize_rendered_html(
        '<a href="https://example.com">x</a>'
    )
    assert 'href="mailto:' in sanitize_rendered_html('<a href="mailto:a@example.invalid">x</a>')
    assert "javascript:" not in sanitize_rendered_html('<a href="javascript:alert(1)">x</a>')
    assert "ftp:" not in sanitize_rendered_html('<a href="ftp://example.invalid/x">x</a>')


def test_the_image_src_policy_is_the_donor_one():
    assert rendering.is_admitted_site_image_src("/wiki/assets/logo.png")
    assert rendering.is_admitted_site_image_src("https://cdn.example.com/img/x.png")
    assert not rendering.is_admitted_site_image_src("/%2e%2e/admin")
    assert not rendering.is_admitted_site_image_src("/\\evil.invalid/x")
    assert not rendering.is_admitted_site_image_src("https://user@evil.invalid/x.png")
    assert not rendering.is_admitted_site_image_src("//cdn.example.com/x.png")
    assert not rendering.is_admitted_site_image_src("images/relative.png")


def test_sanitizing_is_idempotent():
    once = sanitize_rendered_html(
        '<h2 id="setup">Setup</h2><p class="lead">x</p><img src="/a/b.png" alt="">'
    )

    assert sanitize_rendered_html(once) == once


# --- plain text and the document result --------------------------------------


def test_plain_text_is_the_visible_text_of_the_rendered_html():
    document = render_document("## Setup\n\nRun `make`, then **go**.\n")

    assert plain_text(document.html) == "Setup Run make, then go."
    assert document.text == plain_text(document.html)
    assert plain_text("") == ""


def test_an_empty_body_renders_to_nothing():
    document = render_document("")

    assert document.html == ""
    assert document.headings == ()
    assert document.text == ""
    assert render_markdown("") == ""


# --- one renderer, one sanitizer ---------------------------------------------


def test_the_app_modules_re_export_the_shared_renderer():
    from community_base.curriculum import rendering as curriculum_rendering
    from community_base.knowledge_base import rendering as knowledge_base_rendering

    assert knowledge_base_rendering.render_markdown is render_markdown
    assert knowledge_base_rendering.sanitize_rendered_html is sanitize_rendered_html
    assert curriculum_rendering.render_markdown is render_markdown
    assert curriculum_rendering.sanitize_rendered_html is sanitize_rendered_html


# --- the validator's fixtures, rendered ---------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"

FRAGMENT_TARGETS = [
    ("valid_course/01-agentic-rag/02-environment.md", "install-the-tools"),
    ("valid_docs/docs/01-general/01-joining.md", "who-can-join"),
]


def _body(relative_path: str) -> str:
    text = (FIXTURES / relative_path).read_text()
    return text.split("---\n", 2)[2]


@pytest.mark.parametrize(
    ("path", "fragment"), FRAGMENT_TARGETS, ids=[p for p, _ in FRAGMENT_TARGETS]
)
def test_a_fragment_the_validator_resolves_is_an_id_the_renderer_emits(path, fragment):
    """One algorithm: `check_content` accepts these links because the page carries them."""

    assert f'id="{fragment}"' in render_markdown(_body(path))
    assert fragment in {identifier for _, identifier, _ in heading_ids(_body(path))}


def test_the_fences_of_a_valid_fixture_render_to_the_documented_markup():
    rendered = render_markdown(_body("valid_course/01-agentic-rag/01-intro.md"))

    assert '<pre class="mermaid">graph TD; A--&gt;B;</pre>' in rendered
    assert (
        '<div class="cb-embed" data-embed-type="youtube" data-embed-id="rQYyFxf1FWw">'
        '<a href="https://www.youtube.com/watch?v=rQYyFxf1FWw">'
        "https://www.youtube.com/watch?v=rQYyFxf1FWw</a></div>"
    ) in rendered
    # The Liquid inside a fenced block is text, exactly as the validator reads it.
    assert "{% include youtube.html" in rendered
    assert '<code class="language-liquid">' in rendered
