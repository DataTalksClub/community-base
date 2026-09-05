from django.dispatch import Signal, receiver

from community_base.notifications.services import emit_notification_safely

notification_event = Signal()


@receiver(notification_event, dispatch_uid="community_base.notifications.consume_event")
def consume_notification_event(sender, *, source, event, payload=None, **kwargs):
    return emit_notification_safely(source, event, payload)
