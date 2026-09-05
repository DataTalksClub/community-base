"""Audit hook boundary for sensitive Studio actions."""

from community_base.kernel.hooks import Hook


def discard_audit_event(**event) -> None:
    """Default audit writer for sites that have not configured a sink."""


class StudioHooks:
    audit_writer = Hook("STUDIO_AUDIT_WRITER", discard_audit_event)


hooks = StudioHooks()
