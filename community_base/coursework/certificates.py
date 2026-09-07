"""Certificate issuance service.

Ported from the donor ``api/views/enrollment_certificate_updates.py`` and
``enrollment_certificate_delivery.py``. The donor has no certificate model row:
the operator pipeline writes ``Enrollment.certificate_url`` and queues one
availability notification per enrollment that gains a non-empty url. The
package keeps an explicit ``curriculum.Certificate`` row, mirrors the url onto
the legacy ``Enrollment.certificate_url`` reader that every learner surface
reads, and exposes the notification point as the ``certificate_issued`` hook.
No revocation or hash logic: no donor precedent.
"""

from django.db import transaction

from community_base.coursework.hooks import hooks
from community_base.curriculum.models import Certificate, Enrollment


def certificate_for_enrollment(enrollment: Enrollment) -> Certificate | None:
    """Return the enrollment's ``Certificate`` row, or ``None`` when unissued."""

    return Certificate.objects.filter(enrollment=enrollment).first()


@transaction.atomic
def issue_certificate(enrollment: Enrollment, *, url: str) -> tuple[Certificate, bool]:
    """Create or update the enrollment's certificate; return ``(certificate, newly_issued)``.

    ``newly_issued`` is true only when the row is created or its url changed;
    exactly then the ``certificate_issued`` hook fires, matching the donor's
    ``should_notify_certificate_available`` behaviour. Re-issuing with an
    unchanged url writes nothing. The url is mirrored onto
    ``Enrollment.certificate_url``, the column the donor learner surfaces read.
    """
    certificate = certificate_for_enrollment(enrollment)
    if certificate is not None and certificate.url == url:
        return certificate, False
    if certificate is None:
        certificate = Certificate(enrollment=enrollment)
    certificate.url = url
    certificate.save()
    # Donor parity: the learner surfaces read the enrollment column.
    enrollment.certificate_url = url
    enrollment.save(update_fields=["certificate_url"])
    hooks.certificate_issued(certificate=certificate, enrollment=enrollment)
    return certificate, True
