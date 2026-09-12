from django.dispatch import Signal

# Emitted after a Relay callback is verified, deduplicated and projected, once
# per accepted delivery (including replays that changed nothing). Receivers get
# the projected callback facts only: identifiers, safe reason codes, sequence
# and the projected delivery row when the transition belongs to one. Recipient
# addresses never appear in callback payloads, so never add them here.
relay_callback_processed = Signal()
