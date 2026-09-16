from community_base.knowledge_base.rendering import (
    is_admitted_site_image_src,
    render_markdown,
    sanitize_rendered_html,
)


def test_markdown_renders_fenced_code_and_tables():
    html = render_markdown("```python\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<pre>" in html
    assert "<table>" in html


def test_script_tags_are_stripped():
    html = render_markdown("<script>alert(1)</script>\n\nhello")
    assert "<script" not in html
    assert "alert" not in html


def test_event_handler_attributes_are_stripped():
    html = sanitize_rendered_html('<p onclick="evil()">x</p>')
    assert "onclick" not in html


def test_javascript_links_are_removed():
    html = render_markdown("[click](javascript:alert(1))")
    assert "javascript:" not in html


def test_site_absolute_image_is_admitted():
    assert is_admitted_site_image_src("/wiki/assets/logo.png")


def test_absolute_https_image_is_admitted():
    assert is_admitted_site_image_src("https://cdn.example.com/img/x.png")


def test_image_traversal_and_credentials_are_denied():
    assert not is_admitted_site_image_src("/%2e%2e/admin")
    assert not is_admitted_site_image_src("/\\evil.invalid/x")
    assert not is_admitted_site_image_src("https://user@evil.invalid/x.png")
    assert not is_admitted_site_image_src("//cdn.example.com/x.png")


def test_empty_body_renders_empty_html():
    assert render_markdown("") == ""
