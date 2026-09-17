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


def test_heading_ids_and_classes_survive_sanitizing():
    html = sanitize_rendered_html(
        '<div class="toc-body"><h2 id="setup">Setup</h2><p lang="en" title="t">x</p></div>'
    )
    assert (
        html == '<div class="toc-body"><h2 id="setup">Setup</h2><p lang="en" title="t">x</p></div>'
    )


def test_unlisted_attributes_are_still_stripped():
    html = sanitize_rendered_html('<p style="color:red" data-x="1" onmouseover="e()">x</p>')
    assert html == "<p>x</p>"


def test_sanitizing_is_idempotent():
    once = sanitize_rendered_html(
        '<div class="site"><h2 id="a">A</h2><script>alert(1)</script><p>b</p></div>'
    )
    assert sanitize_rendered_html(once) == once
