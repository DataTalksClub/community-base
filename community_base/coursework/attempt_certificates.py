"""Attempt-scoped graduate certificate eligibility, idempotent issuance, and private preview.

This module owns the shared orchestration contract for generating graduate certificates for one
completed dated project attempt:

- Authoritative final attempt pass computation via ``project_results.project_result`` and
  ``project_criteria.settle_completion`` (never preliminary scores or unscoped course-wide scans).
- Respect for any separately configured course completion policy, with explicit reporting when
  the policy excludes learners who passed the project attempt.
- Idempotent, concurrency-safe generation through a site adapter:
  - completed existing certificates are preserved and skipped;
  - revoked certificates are preserved and never overwritten, duplicated, or automatically restored;
  - failed renders keep the reserved credential without a verified attachment so a subsequent click
    retries rendering and persistence without reissuing a new credential;
  - network rendering happens outside DB transactions;
  - no email is ever sent automatically.
- Private preview rendering that never creates credentials or publishes production objects.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from django.core.exceptions import ImproperlyConfigured

from community_base.coursework.integrations import _safe_certificate_url
from community_base.coursework.models import ProjectState
from community_base.coursework.project_criteria import is_review_complete, settle_completion
from community_base.coursework.project_results import project_result
from community_base.kernel.redaction import redact


class CertificateStatus(StrEnum):
    MISSING = "missing"
    PENDING_RENDER = "pending_render"
    ISSUED = "issued"
    REVOKED = "revoked"


@dataclass(frozen=True)
class ExistingCertificate:
    certificate_id: str
    user_id: Any
    attachment_url: str = ""
    is_revoked: bool = False
    issued_at: Any = None
    submission_id: Any = None

    @property
    def status(self) -> CertificateStatus:
        if self.is_revoked:
            return CertificateStatus.REVOKED
        if str(self.attachment_url or "").strip():
            return CertificateStatus.ISSUED
        return CertificateStatus.PENDING_RENDER


@dataclass(frozen=True)
class CompletionPolicyDecision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class AttemptCertificateCandidate:
    submission: Any
    user_id: Any
    passed_attempt: bool
    attempt_score: int | None
    passing_score: int
    reviewed_enough: bool
    policy_allowed: bool
    policy_reason: str
    eligible: bool
    existing: ExistingCertificate | None
    status: CertificateStatus


@dataclass(frozen=True)
class AttemptCertificatePreview:
    attempt_completed: bool
    passing_score: int
    policy_name: str
    total_submissions: int
    passed_attempt_count: int
    excluded_by_policy_count: int
    policy_difference_note: str
    eligible_count: int
    missing_count: int
    missing_new_count: int
    pending_retry_count: int
    already_issued_count: int
    revoked_count: int
    candidates: tuple[AttemptCertificateCandidate, ...]


@dataclass(frozen=True)
class CandidateGenerationOutcome:
    user_id: Any
    submission_id: Any
    action: str
    certificate_id: str = ""
    attachment_url: str = ""
    error: str = ""


@dataclass(frozen=True)
class AttemptCertificateGenerationResult:
    attempt_completed: bool
    eligible_count: int
    created_count: int
    retried_count: int
    skipped_issued_count: int
    skipped_revoked_count: int
    skipped_in_progress_count: int
    failed_count: int
    outcomes: tuple[CandidateGenerationOutcome, ...]
    error: str = ""


@dataclass(frozen=True)
class PrivatePreviewArtifact:
    content: bytes
    content_type: str = "application/pdf"
    filename: str = "certificate-preview.pdf"


class AttemptCertificateAdapter(Protocol):
    """Site-owned persistence and rendering boundary for attempt certificates."""

    def reserve_credential(self, submission: Any) -> tuple[ExistingCertificate, bool]:
        """Return ``(credential, created_new)`` for the submission's user and course.

        Must not overwrite an existing ``attachment_url`` or clear revoked fields.
        """

    def render_attachment(self, submission: Any, credential: ExistingCertificate) -> str:
        """Render and publish the PDF/artifact for ``credential`` and return its public URL."""

    def persist_attachment(
        self,
        submission: Any,
        credential: ExistingCertificate,
        attachment_url: str,
    ) -> bool:
        """Atomically persist ``attachment_url`` only when still unrevoked and unattached."""


def _is_self_paced(project: Any) -> bool:
    if hasattr(project, "uses_pooled_review"):
        return bool(project.uses_pooled_review)
    return bool(getattr(project, "is_self_paced", False))


def is_attempt_completed(project: Any) -> bool:
    """Return True only for a dated project attempt in the ``COMPLETED`` state."""
    if project is None or _is_self_paced(project):
        return False
    state = getattr(project, "state", None)
    if isinstance(state, ProjectState):
        return state == ProjectState.COMPLETED
    return state == ProjectState.COMPLETED.value


def _submission_user_id(submission: Any) -> Any:
    for attr in ("user_id", "student_id"):
        value = getattr(submission, attr, None)
        if value is not None:
            return value
    raise ValueError("Submission has neither user_id nor student_id.")


def _submission_id(submission: Any) -> Any:
    pk = getattr(submission, "pk", None)
    if pk is not None:
        return pk
    return getattr(submission, "id", None)


def _policy_note(
    *,
    policy_name: str,
    passed_attempt_count: int,
    excluded_by_policy_count: int,
) -> str:
    if excluded_by_policy_count > 0:
        label = policy_name or "the configured course completion policy"
        return (
            f"{passed_attempt_count} passed the attempt; "
            f"{excluded_by_policy_count} excluded by {label}."
        )
    if policy_name and passed_attempt_count > 0:
        return (
            f"Course completion policy active: {policy_name} "
            f"(all {passed_attempt_count} attempt passer(s) qualify)."
        )
    if policy_name:
        return f"Course completion policy active: {policy_name}."
    return ""


def evaluate_attempt_certificates(
    project: Any,
    *,
    submissions: Iterable[Any],
    assigned_by_user: Mapping[Any, Iterable[Any]],
    received_by_submission: Mapping[Any, Iterable[Any]],
    criteria: Sequence[dict],
    passing_score: int = 0,
    existing_by_user: Mapping[Any, ExistingCertificate] | None = None,
    completion_policy: Callable[[Any], CompletionPolicyDecision] | None = None,
    policy_name: str = "",
) -> AttemptCertificatePreview:
    """Compute authoritative attempt-scoped certificate eligibility and existing-state counts."""
    submission_list = list(submissions)
    score_threshold = max(0, int(passing_score or 0))
    if not is_attempt_completed(project):
        return AttemptCertificatePreview(
            attempt_completed=False,
            passing_score=score_threshold,
            policy_name=policy_name,
            total_submissions=len(submission_list),
            passed_attempt_count=0,
            excluded_by_policy_count=0,
            policy_difference_note=(
                "Attempt is not completed; certificates can only be generated for a "
                "completed dated attempt."
            ),
            eligible_count=0,
            missing_count=0,
            missing_new_count=0,
            pending_retry_count=0,
            already_issued_count=0,
            revoked_count=0,
            candidates=(),
        )

    criteria_list = list(criteria or ())
    existing_map = existing_by_user or {}
    candidates: list[AttemptCertificateCandidate] = []

    for submission in submission_list:
        user_id = _submission_user_id(submission)
        sub_id = _submission_id(submission)
        settled_assigned = settle_completion(
            assigned_by_user.get(user_id, ()),
            criteria_list,
        )
        reviews_done = sum(1 for review in settled_assigned if is_review_complete(review))
        reviewed_enough = bool(settled_assigned) and reviews_done == len(settled_assigned)

        settled_received = settle_completion(
            received_by_submission.get(sub_id, ()),
            criteria_list,
        )
        complete_received = [review for review in settled_received if is_review_complete(review)]

        result = project_result(
            criteria_list,
            complete_received,
            score_threshold,
            reviewed_enough,
        )
        if score_threshold > 0:
            passed_attempt = bool(result is not None and result.passed is True)
        else:
            passed_attempt = reviewed_enough and bool(complete_received)

        attempt_score = result.total if result is not None else None

        policy_allowed = True
        policy_reason = ""
        if passed_attempt and completion_policy is not None:
            decision = completion_policy(submission)
            policy_allowed = bool(decision.allowed)
            policy_reason = str(decision.reason or "")

        eligible = passed_attempt and policy_allowed
        existing = existing_map.get(user_id)
        if existing is not None and existing.user_id != user_id:
            raise ValueError("Existing certificate user_id does not match the submission user_id.")
        status = CertificateStatus.MISSING if existing is None else existing.status

        candidates.append(
            AttemptCertificateCandidate(
                submission=submission,
                user_id=user_id,
                passed_attempt=passed_attempt,
                attempt_score=attempt_score,
                passing_score=score_threshold,
                reviewed_enough=reviewed_enough,
                policy_allowed=policy_allowed,
                policy_reason=policy_reason,
                eligible=eligible,
                existing=existing,
                status=status,
            )
        )

    passed_attempt_count = sum(1 for item in candidates if item.passed_attempt)
    excluded_by_policy_count = sum(
        1 for item in candidates if item.passed_attempt and not item.policy_allowed
    )
    eligible_items = [item for item in candidates if item.eligible]
    missing_new_count = sum(
        1 for item in eligible_items if item.status == CertificateStatus.MISSING
    )
    pending_retry_count = sum(
        1 for item in eligible_items if item.status == CertificateStatus.PENDING_RENDER
    )
    already_issued_count = sum(
        1 for item in eligible_items if item.status == CertificateStatus.ISSUED
    )
    revoked_count = sum(1 for item in eligible_items if item.status == CertificateStatus.REVOKED)

    return AttemptCertificatePreview(
        attempt_completed=True,
        passing_score=score_threshold,
        policy_name=policy_name,
        total_submissions=len(submission_list),
        passed_attempt_count=passed_attempt_count,
        excluded_by_policy_count=excluded_by_policy_count,
        policy_difference_note=_policy_note(
            policy_name=policy_name,
            passed_attempt_count=passed_attempt_count,
            excluded_by_policy_count=excluded_by_policy_count,
        ),
        eligible_count=len(eligible_items),
        missing_count=missing_new_count + pending_retry_count,
        missing_new_count=missing_new_count,
        pending_retry_count=pending_retry_count,
        already_issued_count=already_issued_count,
        revoked_count=revoked_count,
        candidates=tuple(candidates),
    )


def _candidate_lock(adapter: Any, submission: Any) -> AbstractContextManager[bool]:
    lock_fn = getattr(adapter, "acquire_candidate_lock", None)
    if callable(lock_fn):
        return lock_fn(submission)
    return nullcontext(True)


def _safe_error_text(exc: Exception) -> str:
    return str(redact(str(exc) or type(exc).__name__))


def _process_candidate(
    candidate: AttemptCertificateCandidate,
    adapter: AttemptCertificateAdapter,
) -> CandidateGenerationOutcome:
    sub_id = _submission_id(candidate.submission)
    if candidate.status == CertificateStatus.REVOKED:
        cert_id = candidate.existing.certificate_id if candidate.existing else ""
        return CandidateGenerationOutcome(
            user_id=candidate.user_id,
            submission_id=sub_id,
            action="skipped_revoked",
            certificate_id=cert_id,
        )
    if candidate.status == CertificateStatus.ISSUED:
        cert_id = candidate.existing.certificate_id if candidate.existing else ""
        url = candidate.existing.attachment_url if candidate.existing else ""
        return CandidateGenerationOutcome(
            user_id=candidate.user_id,
            submission_id=sub_id,
            action="skipped_issued",
            certificate_id=cert_id,
            attachment_url=url,
        )

    with _candidate_lock(adapter, candidate.submission) as acquired:
        if not acquired:
            cert_id = candidate.existing.certificate_id if candidate.existing else ""
            return CandidateGenerationOutcome(
                user_id=candidate.user_id,
                submission_id=sub_id,
                action="skipped_in_progress",
                certificate_id=cert_id,
            )

        try:
            credential, created_new = adapter.reserve_credential(candidate.submission)
        except Exception as exc:  # noqa: BLE001
            return CandidateGenerationOutcome(
                user_id=candidate.user_id,
                submission_id=sub_id,
                action="failed",
                error=_safe_error_text(exc),
            )

        if credential.user_id != candidate.user_id:
            return CandidateGenerationOutcome(
                user_id=candidate.user_id,
                submission_id=sub_id,
                action="failed",
                certificate_id=credential.certificate_id,
                error="Reserved credential user does not match submitted user.",
            )

        if credential.is_revoked:
            return CandidateGenerationOutcome(
                user_id=candidate.user_id,
                submission_id=sub_id,
                action="skipped_revoked",
                certificate_id=credential.certificate_id,
            )

        if str(credential.attachment_url or "").strip():
            return CandidateGenerationOutcome(
                user_id=candidate.user_id,
                submission_id=sub_id,
                action="skipped_issued",
                certificate_id=credential.certificate_id,
                attachment_url=credential.attachment_url,
            )

        try:
            raw_url = adapter.render_attachment(candidate.submission, credential)
            verified_url = _safe_certificate_url(raw_url)
        except (ImproperlyConfigured, Exception) as exc:  # noqa: BLE001
            return CandidateGenerationOutcome(
                user_id=candidate.user_id,
                submission_id=sub_id,
                action="failed",
                certificate_id=credential.certificate_id,
                error=_safe_error_text(exc),
            )

        try:
            persisted = bool(
                adapter.persist_attachment(candidate.submission, credential, verified_url)
            )
        except Exception as exc:  # noqa: BLE001
            return CandidateGenerationOutcome(
                user_id=candidate.user_id,
                submission_id=sub_id,
                action="failed",
                certificate_id=credential.certificate_id,
                error=_safe_error_text(exc),
            )

        if not persisted:
            return CandidateGenerationOutcome(
                user_id=candidate.user_id,
                submission_id=sub_id,
                action="skipped_issued",
                certificate_id=credential.certificate_id,
            )

        return CandidateGenerationOutcome(
            user_id=candidate.user_id,
            submission_id=sub_id,
            action="created" if created_new else "retried",
            certificate_id=credential.certificate_id,
            attachment_url=verified_url,
        )


def generate_missing_attempt_certificates(
    preview: AttemptCertificatePreview,
    adapter: AttemptCertificateAdapter,
) -> AttemptCertificateGenerationResult:
    """Generate missing certificates for eligible graduates of one completed attempt.

    Never sends email, never overwrites completed or revoked certificates, and preserves reserved
    credentials across render failures so subsequent retries do not reissue.
    """
    if not preview.attempt_completed:
        return AttemptCertificateGenerationResult(
            attempt_completed=False,
            eligible_count=0,
            created_count=0,
            retried_count=0,
            skipped_issued_count=0,
            skipped_revoked_count=0,
            skipped_in_progress_count=0,
            failed_count=0,
            outcomes=(),
            error="Attempt is not completed; refusing to generate certificates.",
        )

    outcomes: list[CandidateGenerationOutcome] = []
    for candidate in preview.candidates:
        if not candidate.eligible:
            continue
        outcomes.append(_process_candidate(candidate, adapter))

    return AttemptCertificateGenerationResult(
        attempt_completed=True,
        eligible_count=preview.eligible_count,
        created_count=sum(1 for item in outcomes if item.action == "created"),
        retried_count=sum(1 for item in outcomes if item.action == "retried"),
        skipped_issued_count=sum(1 for item in outcomes if item.action == "skipped_issued"),
        skipped_revoked_count=sum(1 for item in outcomes if item.action == "skipped_revoked"),
        skipped_in_progress_count=sum(
            1 for item in outcomes if item.action == "skipped_in_progress"
        ),
        failed_count=sum(1 for item in outcomes if item.action == "failed"),
        outcomes=tuple(outcomes),
    )


def render_private_certificate_preview(
    renderer: Callable[[Any], PrivatePreviewArtifact],
    sample_context: Any,
) -> PrivatePreviewArtifact:
    """Render a private certificate preview without issuing a credential or publishing an object."""
    artifact = renderer(sample_context)
    if not isinstance(artifact, PrivatePreviewArtifact):
        raise TypeError("Private preview renderer must return a PrivatePreviewArtifact.")
    if not isinstance(artifact.content, (bytes, bytearray)) or not artifact.content:
        raise ValueError("Private preview renderer returned empty content.")
    if not str(artifact.content_type or "").strip():
        raise ValueError("Private preview renderer returned an empty content_type.")
    return artifact
