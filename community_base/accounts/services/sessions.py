"""Services over `AccountSession`, the queryable session record.

These are the two operations the donor call sites needed: erase a member's own
sessions (GDPR erasure) and purge sessions that have already expired
(scheduled cleanup). Neither ships as a management command; a site wires each
into whatever scheduler or request-handling code it already has.

Both work regardless of whether a site has opted into the custom
`SessionStore` (`SESSION_ENGINE = "community_base.accounts.session_backend"`).
`purge_expired_sessions` only reads `session_key` and `expire_date`, which
Django's own default backend also writes. `erase_member_sessions` only matches
rows that already carry `account_id`, so before a site opts in it deletes
nothing and returns 0; a site that wants erasure by member must opt in.
"""

from django.utils import timezone

from community_base.accounts.models import AccountSession


def erase_member_sessions(user):
    """Delete every session row recorded for `user`. Returns the row count."""
    deleted, _ = AccountSession.objects.filter(account_id=user.pk).delete()
    return deleted


def purge_expired_sessions(now=None, limit=None):
    """Delete session rows whose `expire_date` is in the past.

    `limit`, when given, bounds how many expired rows a single call deletes,
    so a site's own scheduler can call this repeatedly under its own time or
    batch budget instead of deleting an unbounded number of rows at once.
    Returns the row count deleted by this call.
    """
    now = now or timezone.now()
    expired = AccountSession.objects.filter(expire_date__lt=now)
    if limit is not None:
        session_keys = list(expired.values_list("session_key", flat=True)[:limit])
        deleted, _ = AccountSession.objects.filter(session_key__in=session_keys).delete()
        return deleted
    deleted, _ = expired.delete()
    return deleted
