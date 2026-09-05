from django import template

from community_base.notifications.models import Notification

register = template.Library()


def _count(context):
    request = context.get("request")
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return 0
    return Notification.objects.filter(user=user, read=False).count()


@register.simple_tag(takes_context=True)
def unread_notification_count(context):
    return _count(context)


@register.inclusion_tag("notifications/_bell.html", takes_context=True)
def notification_bell(context):
    return {"unread_count": _count(context)}
