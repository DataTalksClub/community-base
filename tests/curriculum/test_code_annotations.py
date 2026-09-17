"""Structured code annotations: the authoring contract, rendering and sync gate.

The contract is the one specified on AI-Shipping-Labs/website#1589, so a body
authored for one site behaves identically here.
"""

import html
import re
import shutil

import pytest
from django.test import override_settings

from community_base.content_sync.checkout import ImmutableCheckout
from community_base.content_sync.orchestration import sync_content_source
from community_base.curriculum.code_annotations import (
    AnnotatedCodeBlock,
    CodeAnnotation,
    CodeAnnotationError,
    CodeLine,
    build_render_plan,
    parse_annotated_body,
)
from community_base.curriculum.models import Course, Module, Unit
from community_base.curriculum.parsers import parse_course_repository
from community_base.curriculum.rendering import render_annotated_markdown, render_markdown
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.utils import AISL_CONTENT, DTC_REPO, make_source

ANNOTATED_BODY = """Intro.

```python
first = 1

third = first + 2
print(third)
```
<!--
structured: true
code_annotations:
  - line: 1
    text: Set the initial value.
  - lines: "2-3"
    text: >-
      The blank line still counts before the
      calculation on line three.
-->
"""


# --------------------------------------------------------------------------
# Parsing: the authoring contract
# --------------------------------------------------------------------------


def test_valid_payload_is_stripped_and_preserves_ranges_and_note_order():
    parsed = parse_annotated_body(ANNOTATED_BODY)

    assert "structured: true" not in parsed.markdown
    assert "```python" in parsed.markdown
    assert parsed.blocks == (
        AnnotatedCodeBlock(
            language="python",
            lines=(
                CodeLine(1, "first = 1", True),
                CodeLine(2, "", True),
                CodeLine(3, "third = first + 2", True),
                CodeLine(4, "print(third)", False),
            ),
            annotations=(
                CodeAnnotation(1, 1, "Set the initial value."),
                CodeAnnotation(
                    2, 3, "The blank line still counts before the calculation on line three."
                ),
            ),
        ),
    )


def test_annotation_labels_name_a_line_or_an_en_dash_range():
    assert CodeAnnotation(1, 1, "x").label == "Line 1"
    assert CodeAnnotation(2, 3, "x").label == "Lines 2\N{EN DASH}3"


def test_empty_body_parses_to_nothing():
    parsed = parse_annotated_body("")

    assert parsed.markdown == ""
    assert parsed.blocks == ()


def test_quoted_top_level_keys_are_recognized_as_yaml_mapping_keys():
    body = (
        "```text\none\n```\n<!--\n"
        '"structured": true\n"code_annotations":\n'
        "  - line: 1\n    text: Quoted keys are valid YAML.\n-->\n"
    )

    parsed = parse_annotated_body(body)

    assert parsed.blocks[0].annotations == (CodeAnnotation(1, 1, "Quoted keys are valid YAML."),)
    assert "code_annotations" not in parsed.markdown


def test_nested_reserved_key_in_unrelated_comment_is_ignored():
    body = "Before.\n\n<!--\ndocumentation:\n  structured: true\n-->\n"

    parsed = parse_annotated_body(body)

    assert parsed.markdown == body
    assert parsed.blocks == ()


@pytest.mark.parametrize("key", ['"structured"', "'code_annotations'"])
def test_quoted_reserved_keys_are_rejected_in_inline_comments(key):
    body = f"```text\none\n```\n<!-- {key}: true -->\n"

    with pytest.raises(CodeAnnotationError, match="standalone multi-line HTML comment"):
        parse_annotated_body(body)


def test_multiple_blocks_keep_separate_annotation_groups():
    body = (
        "```python\na = 1\n```\n"
        "<!--\nstructured: true\ncode_annotations:\n"
        "  - line: 1\n    text: First block.\n-->\n\n"
        "Between.\n\n"
        "```bash\necho second\n```\n"
        "<!--\nstructured: true\ncode_annotations:\n"
        "  - line: 1\n    text: Second block.\n-->\n"
    )

    parsed = parse_annotated_body(body)

    assert [block.annotations for block in parsed.blocks] == [
        (CodeAnnotation(1, 1, "First block."),),
        (CodeAnnotation(1, 1, "Second block."),),
    ]


def test_unannotated_block_is_listed_as_none_and_prose_is_untouched():
    body = (
        '```python {highlight="1"}\nprint("legacy")\n```\n\n'
        "<!-- code-annotations -->\n\n"
        "- Line 1: legacy note\n\n"
        "<!-- editorial: keep this comment -->\n"
    )

    parsed = parse_annotated_body(body)

    assert parsed.markdown == body
    assert parsed.blocks == (None,)


INVALID_BODIES = {
    "malformed YAML": (
        "```text\none\n```\n<!--\nstructured: true\ncode_annotations: [unterminated\n-->\n"
    ),
    "duplicate mapping key": (
        "```text\none\n```\n<!--\nstructured: true\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: Duplicate key.\n-->\n"
    ),
    "unclosed comment": (
        "```text\none\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: Missing close.\n"
    ),
    "inline candidate comment": (
        "```text\none\n```\n<!-- structured: true, code_annotations: [] -->\n"
    ),
    "missing required key": "```text\none\n```\n<!--\nstructured: true\n-->\n",
    "wrong structured value": (
        "```text\none\n```\n<!--\nstructured: false\n"
        "code_annotations:\n  - line: 1\n    text: Bad marker.\n-->\n"
    ),
    "empty note": (
        "```text\none\n```\n<!--\nstructured: true\n"
        'code_annotations:\n  - line: 1\n    text: "  "\n-->\n'
    ),
    "mixed selectors": (
        "```text\none\ntwo\n```\n<!--\nstructured: true\n"
        'code_annotations:\n  - line: 1\n    lines: "1-2"\n    text: Ambiguous.\n-->\n'
    ),
    "no selector": (
        "```text\none\n```\n<!--\nstructured: true\ncode_annotations:\n  - text: Which line?\n-->\n"
    ),
    "non-integer line": (
        "```text\none\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: true\n    text: Boolean.\n-->\n"
    ),
    "unquoted range": (
        "```text\none\ntwo\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - lines: 1-2\n    text: Bad.\n-->\n"
    ),
    "reversed range": (
        "```text\none\ntwo\n```\n<!--\nstructured: true\n"
        'code_annotations:\n  - lines: "2-1"\n    text: Backwards.\n-->\n'
    ),
    "overlap": (
        "```text\none\ntwo\nthree\n```\n<!--\nstructured: true\n"
        'code_annotations:\n  - lines: "1-2"\n    text: First.\n'
        '  - lines: "2-3"\n    text: Second.\n-->\n'
    ),
    "out of range": (
        "```text\none\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 2\n    text: Missing.\n-->\n"
    ),
    "prose separated": (
        "```text\none\n```\nProse.\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: Orphan.\n-->\n"
    ),
    "no preceding fence": (
        "Prose only.\n\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: Orphan.\n-->\n"
    ),
    "special fence": (
        "```mermaid\nflowchart LR\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: Invalid target.\n-->\n"
    ),
    "duplicate payload": (
        "```text\none\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: First.\n-->\n"
        "<!--\nstructured: true\ncode_annotations:\n"
        "  - line: 1\n    text: Duplicate.\n-->\n"
    ),
    "unknown annotation key": (
        "```text\none\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: Note.\n    html: true\n-->\n"
    ),
    "empty annotation sequence": (
        "```text\none\n```\n<!--\nstructured: true\ncode_annotations: []\n-->\n"
    ),
    "annotation item is not a mapping": (
        "```text\none\n```\n<!--\nstructured: true\ncode_annotations:\n  - just a string\n-->\n"
    ),
    "unsafe YAML tag": (
        "```text\none\n```\n<!--\nstructured: true\ncode_annotations:\n  - line: 1\n"
        "    text: !!python/object/apply:os.system [id]\n-->\n"
    ),
}


@pytest.mark.parametrize("label", sorted(INVALID_BODIES))
def test_invalid_payloads_are_rejected(label):
    with pytest.raises(CodeAnnotationError):
        parse_annotated_body(INVALID_BODIES[label])


def test_a_comment_inside_an_unclosed_fence_is_code_not_metadata():
    body = "```text\n<!--\nstructured: true\ncode_annotations:\n  - line: 1\n    text: Code.\n"

    parsed = parse_annotated_body(body)

    assert parsed.markdown == body
    assert parsed.blocks == ()


# --------------------------------------------------------------------------
# The rendering seam
# --------------------------------------------------------------------------


def test_render_plan_replaces_only_annotated_fences_with_a_token():
    plan = build_render_plan(ANNOTATED_BODY)

    assert len(plan.blocks) == 1
    token, block = plan.blocks[0]
    assert token in plan.markdown
    assert "```python" not in plan.markdown
    assert block.language == "python"


def test_render_plan_keeps_the_fence_indentation_on_the_token():
    body = (
        "  ```text\n  value\n  ```\n"
        "  <!--\n  structured: true\n  code_annotations:\n"
        "    - line: 1\n      text: Indented.\n  -->\n"
    )

    plan = build_render_plan(body)

    token, _block = plan.blocks[0]
    assert f"  {token}" in plan.markdown


# --------------------------------------------------------------------------
# Rendering through the default template
# --------------------------------------------------------------------------


def test_annotated_block_renders_numbered_lines_and_accessible_ordered_notes():
    rendered = render_annotated_markdown(ANNOTATED_BODY)

    assert 'class="annotated-code-block"' in rendered
    assert 'class="code-line-gutter" aria-hidden="true"' in rendered
    assert rendered.count('class="code-line-number"') == 4
    assert rendered.count("is-highlighted") == 3
    assert '<ol class="code-annotation-list">' in rendered
    assert rendered.index("Line 1:") < rendered.index("Lines 2\N{EN DASH}3:")
    assert "structured: true" not in rendered

    code_match = re.search(r"<code[^>]*>(?P<code>.*?)</code>", rendered, re.DOTALL)
    code_text = html.unescape(re.sub(r"<[^>]+>", "", code_match.group("code")))
    assert code_text == "first = 1\n\nthird = first + 2\nprint(third)"
    assert "Set the initial value." not in code_match.group("code")


def test_language_is_exposed_for_site_side_syntax_highlighting():
    rendered = render_annotated_markdown(ANNOTATED_BODY)

    assert '<code class="language-python">' in rendered


def test_note_text_is_plain_escaped_text():
    body = (
        "```text\nvalue\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n"
        '    text: "[Guide](https://example.com/note) '
        '<img src=x onerror=alert(1)> & explain"\n-->\n'
    )

    rendered = render_annotated_markdown(body)

    notes_html = rendered[rendered.index("<aside") :]
    assert "<a " not in notes_html
    assert "[Guide](https://example.com/note)" in notes_html
    assert "&lt;img src=x onerror=alert(1)&gt; &amp; explain" in rendered
    assert "<img src=x" not in rendered


def test_code_text_is_escaped():
    body = (
        "```html\n<script>alert(1)</script>\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: Escaped.\n-->\n"
    )

    rendered = render_annotated_markdown(body)

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<script>" not in rendered


def test_unannotated_body_renders_through_the_one_markdown_path():
    body = 'Before.\n\n```python\nprint("same")\n```\n'

    assert render_annotated_markdown(body) == render_markdown(body)


def test_empty_body_renders_empty():
    assert render_annotated_markdown("") == ""


def test_two_annotated_blocks_get_distinct_heading_ids():
    body = (
        "```text\none\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: First.\n-->\n\n"
        "Between.\n\n"
        "```text\ntwo\n```\n<!--\nstructured: true\n"
        "code_annotations:\n  - line: 1\n    text: Second.\n-->\n"
    )

    rendered = render_annotated_markdown(body)

    assert 'id="code-annotations-1"' in rendered
    assert 'id="code-annotations-2"' in rendered


def test_prose_around_an_annotated_block_survives():
    body = "Here is the code:\n\n" + ANNOTATED_BODY + "\nAfter.\n"

    rendered = render_annotated_markdown(body)

    assert "<p>Here is the code:</p>" in rendered
    assert "<p>After.</p>" in rendered


def test_a_site_may_override_the_default_template(tmp_path, settings):
    override_dir = tmp_path / "templates" / "curriculum"
    override_dir.mkdir(parents=True)
    (override_dir / "annotated_code_block.html").write_text(
        '<div class="site-owned">{{ block.annotations|length }} notes</div>'
    )
    templates = [dict(settings.TEMPLATES[0])]
    templates[0]["DIRS"] = [str(tmp_path / "templates"), *templates[0]["DIRS"]]

    with override_settings(TEMPLATES=templates):
        rendered = render_annotated_markdown(ANNOTATED_BODY)

    assert '<div class="site-owned">2 notes</div>' in rendered
    assert "annotated-code-block" not in rendered


# --------------------------------------------------------------------------
# The unit save path
# --------------------------------------------------------------------------


@pytest.fixture
def module(db):
    course = Course.objects.create(title="Annotation Course", slug="annotation-course")
    return Module.objects.create(course=course, title="Module", slug="module", sort_order=1)


def test_unit_preserves_source_body_and_derives_annotation_html(module):
    unit = Unit.objects.create(
        module=module, title="Annotated unit", slug="annotated-unit", body=ANNOTATED_BODY
    )

    assert unit.body == ANNOTATED_BODY
    assert "annotated-code-block" in unit.body_html
    assert "structured: true" not in unit.body_html


def test_invalid_update_does_not_replace_a_persisted_unit(module):
    unit = Unit.objects.create(
        module=module, title="Stable unit", slug="stable-unit", body="Previous valid lesson."
    )
    old_html = unit.body_html
    unit.body = INVALID_BODIES["out of range"]

    with pytest.raises(CodeAnnotationError):
        unit.save()

    persisted = Unit.objects.get(pk=unit.pk)
    assert persisted.body == "Previous valid lesson."
    assert persisted.body_html == old_html


# --------------------------------------------------------------------------
# The sync gate: a malformed payload fails the import, naming the file
# --------------------------------------------------------------------------


def _copy(fixture, tmp_path, name):
    target = tmp_path / name
    shutil.copytree(fixture, target)
    return target


def test_sync_rejects_a_malformed_payload_and_names_the_file(tmp_path):
    root = _copy(AISL_CONTENT, tmp_path, "aisl")
    unit = root / "courses" / "ai-hero" / "01-welcome" / "01-setup.md"
    unit.write_text(unit.read_text() + "\n" + INVALID_BODIES["out of range"])

    with ImmutableCheckout(root) as active:
        with pytest.raises(CurriculumParseError) as error:
            parse_course_repository(active, path="courses/ai-hero")

    assert "courses/ai-hero/01-welcome/01-setup.md" in str(error.value)
    assert "visible lines" in str(error.value)


def test_sync_accepts_a_valid_payload(tmp_path):
    root = _copy(AISL_CONTENT, tmp_path, "aisl-valid")
    unit = root / "courses" / "ai-hero" / "01-welcome" / "01-setup.md"
    unit.write_text(unit.read_text() + "\n" + ANNOTATED_BODY)

    with ImmutableCheckout(root) as active:
        parsed = parse_course_repository(active, path="courses/ai-hero")

    bodies = [
        unit_graph.body
        for module_graph in parsed.course.modules
        for unit_graph in module_graph.units
    ]
    assert any("structured: true" in body for body in bodies)


def test_a_special_fence_annotation_is_rejected_and_the_file_named(tmp_path):
    root = _copy(DTC_REPO, tmp_path, "dtc")
    lesson = root / "01-core" / "01-lesson.md"
    lesson.write_text(lesson.read_text() + "\n" + INVALID_BODIES["special fence"])

    with ImmutableCheckout(root) as active:
        with pytest.raises(CurriculumParseError) as error:
            parse_course_repository(active)

    assert "01-core/01-lesson.md" in str(error.value)
    assert "special fences cannot have annotations" in str(error.value)


@pytest.mark.django_db
def test_a_malformed_payload_fails_the_whole_sync(tmp_path):
    root = _copy(AISL_CONTENT, tmp_path, "aisl-sync")
    unit = root / "courses" / "ai-hero" / "01-welcome" / "01-setup.md"
    unit.write_text(unit.read_text() + "\n" + INVALID_BODIES["duplicate payload"])
    source = make_source(slug="annotations-source", repo="example/annotations")

    log = sync_content_source(source, repo_dir=str(root))

    assert log.status != "success"
    assert Course.objects.filter(slug="ai-hero").count() == 0


@pytest.mark.django_db
def test_a_valid_payload_syncs_end_to_end_and_renders(tmp_path):
    root = _copy(AISL_CONTENT, tmp_path, "aisl-ok")
    unit = root / "courses" / "ai-hero" / "01-welcome" / "01-setup.md"
    unit.write_text(unit.read_text() + "\n" + ANNOTATED_BODY)
    source = make_source(slug="annotations-ok", repo="example/annotations-ok")

    sync_content_source(source, repo_dir=str(root))

    synced = Unit.objects.get(title="Setup")
    assert "structured: true" in synced.body
    assert 'class="annotated-code-block"' in synced.body_html
    assert '<span class="code-annotation-line is-highlighted" data-line-number="1">' in (
        synced.body_html
    )
    assert "Set the initial value." in synced.body_html
    assert "structured: true" not in synced.body_html


@pytest.mark.django_db
def test_an_invalid_replacement_leaves_the_published_units_untouched(tmp_path):
    root = _copy(AISL_CONTENT, tmp_path, "aisl-replace")
    source = make_source(slug="annotations-replace", repo="example/annotations-replace")
    sync_content_source(source, repo_dir=str(root))
    published = {unit.pk: (unit.body, unit.body_html) for unit in Unit.objects.all()}
    assert published

    unit_path = root / "courses" / "ai-hero" / "01-welcome" / "01-setup.md"
    unit_path.write_text(unit_path.read_text() + "\n" + INVALID_BODIES["overlap"])
    log = sync_content_source(source, repo_dir=str(root))

    assert log.status != "success"
    assert {unit.pk: (unit.body, unit.body_html) for unit in Unit.objects.all()} == published
