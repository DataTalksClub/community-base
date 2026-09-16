"""Certificate eligibility, request-based issuance, and artifact generation.

Issuance itself (``issue_certificate``) is ported from the donor
``api/views/enrollment_certificate_updates.py`` and ``enrollment_certificate_delivery.py``. The
donor has no certificate model row: the operator pipeline writes ``Enrollment.certificate_url``
and queues one availability notification per enrollment that gains a non-empty url. The package
keeps an explicit ``curriculum.Certificate`` row, mirrors the url onto the legacy
``Enrollment.certificate_url`` reader that every learner surface reads, and exposes the
notification point as the ``certificate_issued`` hook. No revocation or hash logic: no donor
precedent.

``certificate_eligibility`` and ``request_certificate`` are new (C5.2h): the package has never had
automatic issuance or an eligibility check of its own -- both existed only in the AISL donor
(``check_certificate_eligibility``, ``issue_certificates_for_course`` in
``content/services/peer_review_service.py``), which never got ported. "Certificate on request
rather than automatic" is therefore a package feature addition, not a behaviour change within the
package; the behaviour change is on AISL's own site, which retires its local automatic issuance
separately (A5.1).
"""

from dataclasses import dataclass

from django.db import transaction

from community_base.coursework.hooks import hooks
from community_base.coursework.integrations import generate_certificate_artifact
from community_base.coursework.models import ProjectSubmission
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


@dataclass(frozen=True)
class CertificateEligibility:
    eligible: bool
    reasons: tuple[str, ...]


def certificate_eligibility(enrollment: Enrollment) -> CertificateEligibility:
    """Whether ``enrollment`` currently qualifies to request a certificate.

    Generalizes the AISL donor's four conditions (all course units completed, a project
    submitted, the learner's own assigned reviews given, and every review on their submission
    complete) to the package's richer model, mode-agnostic -- identical for a dated cohort or a
    pooled project:

    - Every countable unit of the enrollment's course completed (``Course.total_units``/
      ``completed_units``, which already excludes bonus content and checklist items -- the donor's
      first condition).
    - At least ``cohort.min_projects_to_pass`` of the enrollment's project submissions ``passed``.
      ``passed`` is already ``project_score >= points_to_pass AND reviewed_enough_peers``
      (``review.score_submission``), which covers the donor's remaining three conditions in one
      field: a submission only reaches ``passed`` once it has been scored (submitted, reviewed)
      and its owner gave their own assigned reviews. No separate review-completion check is
      needed.

    Homework is deliberately not a gate here: the donor's own eligibility check has none either.
    """

    reasons: list[str] = []
    cohort = enrollment.cohort
    course = cohort.course

    total_units = course.total_units()
    completed_units = course.completed_units(enrollment.user)
    if total_units == 0:
        reasons.append("The course has no units to complete.")
    elif completed_units < total_units:
        reasons.append(f"{completed_units} of {total_units} units completed.")

    passed_count = ProjectSubmission.objects.filter(
        enrollment=enrollment, passed=True, volunteer_review_only=False
    ).count()
    required = cohort.min_projects_to_pass
    if passed_count < required:
        reasons.append(f"{passed_count} of {required} required projects passed.")

    return CertificateEligibility(eligible=not reasons, reasons=tuple(reasons))


def request_certificate(
    enrollment: Enrollment,
) -> tuple[Certificate | None, CertificateEligibility]:
    """Issue a certificate for ``enrollment`` if it currently qualifies.

    Returns ``(certificate, eligibility)``; ``certificate`` is ``None`` when ineligible, with
    ``eligibility.reasons`` explaining why. Idempotent for an already-issued certificate: an
    eligible enrollment that already has one gets its artifact (re)generated and attached rather
    than being refused as "already issued" (recommended default for learners grandfathered from
    AISL's prior automatic issuance -- surfaced to the owner in DataTalksClub/community-base#256,
    not decided unilaterally here; A5.1 applies whatever the owner confirms to AISL's existing
    rows).
    """

    eligibility = certificate_eligibility(enrollment)
    if not eligibility.eligible:
        return None, eligibility

    url = generate_certificate_artifact(enrollment, certificate_for_enrollment(enrollment))
    certificate, _newly_issued = issue_certificate(enrollment, url=url)
    return certificate, eligibility
