"""Include containers and media hooks obey the one shared HTML contract."""

import pytest

from community_base.content_sync.rendering import render_document, sanitize_rendered_html


@pytest.mark.parametrize(
    "markup",
    [
        '<section id="stages"><h2 id="learn">Learn</h2><p>Stages</p></section>',
        "<aside>Article-local callout</aside>",
    ],
)
def test_host_include_containers_survive_final_sanitization(markup):
    assert sanitize_rendered_html(markup) == markup
    assert sanitize_rendered_html(sanitize_rendered_html(markup)) == markup


@pytest.mark.parametrize("provider", ["youtube", "loom"])
def test_shared_media_hooks_remain_intact_without_stored_iframes(provider):
    body = f"```embed\ntype: {provider}\nid: abc123\n```"
    rendered = render_document(body).html
    assert f'data-embed-type="{provider}"' in rendered
    assert 'data-embed-id="abc123"' in rendered
    assert '<div class="cb-embed"' in rendered
    assert "<a href=" in rendered
    assert "<iframe" not in rendered
    assert sanitize_rendered_html(rendered) == rendered


@pytest.mark.parametrize(
    "source",
    [
        "https://www.youtube.com/embed/abc123?enablejsapi=1&amp;rel=0",
        "https://www.loom.com/embed/abc123",
        "javascript:alert(1)",
        "data:text/html,unsafe",
    ],
)
def test_stored_iframes_remain_excluded(source):
    rendered = sanitize_rendered_html(f'<iframe src="{source}" srcdoc="unsafe"></iframe>')
    assert "iframe" not in rendered
    assert "srcdoc" not in rendered


def test_include_containers_do_not_admit_executable_attributes_or_elements():
    markup = (
        '<section onclick="alert(1)"><script>alert(2)</script>'
        '<style>body{display:none}</style><aside style="display:none" '
        'onmouseover="alert(3)">Callout</aside></section>'
    )
    assert sanitize_rendered_html(markup) == "<section><aside>Callout</aside></section>"
