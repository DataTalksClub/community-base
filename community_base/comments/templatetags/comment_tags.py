from django import template

register = template.Library()


@register.inclusion_tag("comments/_thread.html", takes_context=True)
def comment_thread(context, content_id):
    return {"request": context.get("request"), "content_id": content_id}
