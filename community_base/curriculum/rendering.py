"""Curriculum rendering: structured code annotations on top of the shared renderer.

Issue C7.8 moved markdown, sanitizing, heading ids and the leading-H1 rule to
``community_base.content_sync.rendering``, the one renderer and the one
sanitizer (`FORMAT.md` section 4.2). This module owns the curriculum-specific
entry point.

``render_annotated_markdown`` is the unit-body entry point: it adds structured
code annotations (``community_base.curriculum.code_annotations``) on top of the
one markdown path. There is still no second renderer and no second sanitizer --
the annotated block is markup this package generates from a parsed structure
after sanitization, through a template a site may override.
"""

from django.template.loader import render_to_string

from community_base.content_sync.rendering import render_markdown as _render_markdown
from community_base.curriculum.code_annotations import build_render_plan

__all__ = [
    "ANNOTATED_CODE_BLOCK_HEADING",
    "ANNOTATED_CODE_BLOCK_TEMPLATE",
    "render_annotated_markdown",
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
    rendered = _render_markdown(plan.markdown)
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
