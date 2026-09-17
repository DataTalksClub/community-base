"""Knowledge base rendering: the shared renderer, under its historic name.

Issue C7.8 moved the implementation to
``community_base.content_sync.rendering``, the one renderer and the one
sanitizer for synced content (`FORMAT.md` section 4.2). This module stays as the
import path existing callers and sites already use.
"""

from community_base.content_sync.rendering import (
    inject_heading_ids,
    is_admitted_site_image_src,
    plain_text,
    render_document,
    render_markdown,
    sanitize_rendered_html,
)

__all__ = [
    "inject_heading_ids",
    "is_admitted_site_image_src",
    "plain_text",
    "render_document",
    "render_markdown",
    "sanitize_rendered_html",
]
