from django.dispatch import Signal

event_cancelled = Signal()
event_published = Signal()
event_rescheduled = Signal()
