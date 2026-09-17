"""Curriculum rendering: the shared renderer plus structured code annotations.

Issue C7.8 moved markdown, sanitizing, heading ids and the leading-H1 rule to
``community_base.content_sync.rendering``, the one renderer and the one
sanitizer (`FORMAT.md` section 4.2). This module keeps the curriculum-specific
entry point and re-exports the shared names, so existing imports keep working.

``render_annotated_markdown`` is the unit-body entry point: it adds structured
code annotations (``community_base.curriculum.code_annotations``) on top of the
one markdown path. There is still no second renderer and no second sanitizer --
the annotated block is markup this package generates from a parsed structure
after sanitization, through a template a site may override.
"""

from django.template.loader import render_to_string

from community_base.content_sync.rendering import (
    inject_heading_ids,
    plain_text,
    render_document,
    render_markdown,
    sanitize_rendered_html,
    strip_leading_title_h1,
)
from community_base.curriculum.code_annotations import build_render_plan

__all__ = [
    "ANNOTATED_CODE_BLOCK_HEADING",
    "ANNOTATED_CODE_BLOCK_TEMPLATE",
    "inject_heading_ids",
    "plain_text",
    "render_annotated_markdown",
    "render_document",
    "render_markdown",
    "sanitize_rendered_html",
    "strip_leading_title_h1",
]

ANNOTATED_CODE_BLOCK_TEMPLATE = "curriculum/annotated_code_block.html"
ANNOTATED_CODE_BLOCK_HEADING = "Code annotations"


def render_annotated_markdown(text: str) -> str:
    """Render a unit body, expanding annotated code blocks into their markup.

    Bodies with no annotations render exactly like ``render_markdown``. An
    invalid annotation payload raises ``CodeAnnotationError`` so a malformed
    body fails rather than being published with its metadata showing.
    """

    if not text:
        return ""
    plan = build_render_plan(text)
    rendered = render_markdown(plan.markdown)
    for position, (token, block) in enumerate(plan.blocks, start=1):
        markup = render_to_string(
            ANNOTATED_CODE_BLOCK_TEMPLATE,
            {
                "block": block,
                "heading": ANNOTATED_CODE_BLOCK_HEADING,
                "heading_id": f"code-annotations-{position}",
            },
        ).strip()
        paragraph = f"<p>{token}</p>"
        if paragraph in rendered:
            rendered = rendered.replace(paragraph, markup, 1)
        else:
            rendered = rendered.replace(token, markup, 1)
    return rendered
