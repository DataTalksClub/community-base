"""C7.31: the unsubscribe primary action is findable before a site styles it."""

from django.template.loader import render_to_string


def test_the_unsubscribe_submit_is_a_block_after_the_fields():
    html = render_to_string(
        "community_base/mail/unsubscribe.html",
        {
            "scope_choices": (("all", "All email"), ("events", "Events")),
        },
    )

    field_close = html.rindex("</div>")
    button_open = html.index("cb-button-primary")
    assert field_close < button_open
    assert '<div class="cb-field">' in html
    assert '<p><button class="cb-button cb-button-primary"' in html
    assert "cb-button-primary" not in html[html.index("<form") : field_close]
