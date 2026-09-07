"""Narrow lifecycle-policy corrections for the governed real-time call path."""

from .call_control import ALLOWED_TRANSITIONS


# Asterisk can emit an offered event before the first explicit ringing event.
# The transition remains monotonic and does not permit any terminal regression.
ALLOWED_TRANSITIONS["offered"].add("ringing")
