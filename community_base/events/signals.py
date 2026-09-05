from django.dispatch import Signal

event_cancelled = Signal()
event_published = Signal()
event_registered = Signal()
event_rescheduled = Signal()
event_unregistered = Signal()
