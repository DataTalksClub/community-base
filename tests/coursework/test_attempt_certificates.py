"""Tests for attempt-scoped graduate certificate orchestration (intake 32366cde)."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from community_base.coursework.attempt_certificates import (
    CertificateStatus,
    CompletionPolicyDecision,
    ExistingCertificate,
    PrivatePreviewArtifact,
    evaluate_attempt_certificates,
    generate_missing_attempt_certificates,
    is_attempt_completed,
    render_private_certificate_preview,
)
from community_base.coursework.models import ProjectState

CRITERIA = [
    {
        "id": "quality",
        "title": "Code quality",
        "type": "scale",
        "options": [
            {"text": "Missing", "points": 0},
            {"text": "Partial", "points": 5},
            {"text": "Complete", "points": 10},
        ],
    },
]


def _project(*, state=ProjectState.COMPLETED.value, self_paced=False):
    return SimpleNamespace(pk=1, state=state, is_self_paced=self_paced)


def _submission(pk: int, user_id: int):
    return SimpleNamespace(pk=pk, user_id=user_id)


def _review(*, complete=True, score_index=2):
    return SimpleNamespace(
        is_complete=complete,
        criteria_scores={"quality": score_index} if score_index is not None else {},
    )


class FakeCertificateAdapter:
    """In-memory thread-safe fake adapter mirroring DB credential + render provider behavior."""

    def __init__(
        self,
        *,
        existing: dict[int, ExistingCertificate] | None = None,
        fail_users: set[int] | None = None,
        return_url_override: dict[int, str] | None = None,
        mismatch_user: int | None = None,
        render_delay: float = 0.0,
        use_locks: bool = True,
    ):
        self._lock = threading.Lock()
        self._active_users: set[int] = set()
        self.credentials: dict[int, ExistingCertificate] = dict(existing or {})
        self.fail_users: set[int] = set(fail_users or ())
        self.return_url_override: dict[int, str] = dict(return_url_override or {})
        self.mismatch_user = mismatch_user
        self.render_delay = render_delay
        self.use_locks = use_locks
        self.render_calls: list[tuple[int, str]] = []
        self.reserve_calls: list[int] = []
        self.persist_calls: list[tuple[int, str, str]] = []
        self.mail_calls: int = 0
        self._next_seq = 1

    @contextmanager
    def acquire_candidate_lock(self, submission):
        if not self.use_locks:
            yield True
            return
        with self._lock:
            if submission.user_id in self._active_users:
                acquired = False
            else:
                self._active_users.add(submission.user_id)
                acquired = True
        try:
            yield acquired
        finally:
            if acquired:
                with self._lock:
                    self._active_users.discard(submission.user_id)

    def reserve_credential(self, submission):
        with self._lock:
            self.reserve_calls.append(submission.user_id)
            if self.mismatch_user == submission.user_id:
                return ExistingCertificate(
                    certificate_id="wrong-user-cert",
                    user_id=99999,
                    attachment_url="",
                ), False
            existing = self.credentials.get(submission.user_id)
            if existing is not None:
                return existing, False
            cert = ExistingCertificate(
                certificate_id=f"cert-{self._next_seq}",
                user_id=submission.user_id,
                attachment_url="",
                submission_id=submission.pk,
            )
            self._next_seq += 1
            self.credentials[submission.user_id] = cert
            return cert, True

    def render_attachment(self, submission, credential: ExistingCertificate) -> str:
        if self.render_delay:
            time.sleep(self.render_delay)
        with self._lock:
            self.render_calls.append((submission.user_id, credential.certificate_id))
            should_fail = submission.user_id in self.fail_users
            override = self.return_url_override.get(submission.user_id)
        if should_fail:
            raise RuntimeError("banner-generator 502 upstream timeout")
        if override is not None:
            return override
        return f"https://cdn.example.com/banners/certificates/{credential.certificate_id}.pdf"

    def persist_attachment(
        self, submission, credential: ExistingCertificate, attachment_url: str
    ) -> bool:
        with self._lock:
            current = self.credentials.get(submission.user_id)
            if current is None or current.is_revoked or current.attachment_url:
                return False
            self.credentials[submission.user_id] = ExistingCertificate(
                certificate_id=current.certificate_id,
                user_id=current.user_id,
                attachment_url=attachment_url,
                is_revoked=False,
                issued_at=current.issued_at,
                submission_id=current.submission_id,
            )
            self.persist_calls.append(
                (submission.user_id, credential.certificate_id, attachment_url)
            )
            return True


def test_non_completed_and_self_paced_attempts_are_rejected():
    sub = _submission(1, 10)
    for project in (
        _project(state=ProjectState.COLLECTING_SUBMISSIONS.value),
        _project(state=ProjectState.PEER_REVIEWING.value),
        _project(state=ProjectState.CLOSED.value),
        _project(state=ProjectState.COMPLETED.value, self_paced=True),
    ):
        assert not is_attempt_completed(project)
        preview = evaluate_attempt_certificates(
            project,
            submissions=[sub],
            assigned_by_user={10: [_review()]},
            received_by_submission={1: [_review()]},
            criteria=CRITERIA,
            passing_score=8,
        )
        assert not preview.attempt_completed
        assert preview.eligible_count == 0
        assert preview.missing_count == 0

        adapter = FakeCertificateAdapter()
        result = generate_missing_attempt_certificates(preview, adapter)
        assert not result.attempt_completed
        assert result.error
        assert adapter.reserve_calls == []
        assert adapter.render_calls == []


def test_authoritative_pass_requires_passing_score_and_completed_assigned_reviews():
    # User 10: score 10 >= 8, all assigned reviews done -> PASS
    # User 20: score 5 < 8, all assigned reviews done -> FAIL
    # User 30: score 10 >= 8, assigned review incomplete -> FAIL
    # User 40: score 10 >= 8, missing criteria answer -> settled incomplete -> FAIL
    subs = [_submission(1, 10), _submission(2, 20), _submission(3, 30), _submission(4, 40)]
    preview = evaluate_attempt_certificates(
        _project(),
        submissions=subs,
        assigned_by_user={
            10: [_review(complete=True, score_index=2)],
            20: [_review(complete=True, score_index=2)],
            30: [_review(complete=False, score_index=2)],
            40: [_review(complete=True, score_index=None)],
        },
        received_by_submission={
            1: [_review(complete=True, score_index=2)],
            2: [_review(complete=True, score_index=1)],
            3: [_review(complete=True, score_index=2)],
            4: [_review(complete=True, score_index=2)],
        },
        criteria=CRITERIA,
        passing_score=8,
    )

    assert preview.attempt_completed
    assert preview.total_submissions == 4
    assert preview.passed_attempt_count == 1
    assert preview.eligible_count == 1
    assert preview.missing_count == 1
    by_user = {c.user_id: c for c in preview.candidates}
    assert by_user[10].passed_attempt and by_user[10].eligible
    assert not by_user[20].passed_attempt
    assert not by_user[30].passed_attempt
    assert not by_user[40].passed_attempt


def test_course_completion_policy_respected_and_differences_communicated():
    subs = [_submission(1, 10), _submission(2, 20)]

    def policy(submission):
        if submission.user_id == 10:
            return CompletionPolicyDecision(allowed=True)
        return CompletionPolicyDecision(allowed=False, reason="2 of 5 required units completed.")

    preview = evaluate_attempt_certificates(
        _project(),
        submissions=subs,
        assigned_by_user={10: [_review()], 20: [_review()]},
        received_by_submission={1: [_review()], 2: [_review()]},
        criteria=CRITERIA,
        passing_score=8,
        completion_policy=policy,
        policy_name="All required course units completed",
    )

    assert preview.passed_attempt_count == 2
    assert preview.excluded_by_policy_count == 1
    assert preview.eligible_count == 1
    assert preview.missing_count == 1
    assert "2 passed the attempt; 1 excluded by All required course units completed." in (
        preview.policy_difference_note
    )

    adapter = FakeCertificateAdapter()
    result = generate_missing_attempt_certificates(preview, adapter)
    assert result.created_count == 1
    assert list(adapter.credentials.keys()) == [10]


def test_duplicate_clicks_only_create_missing_and_preserve_existing_and_revoked():
    existing_issued = ExistingCertificate(
        certificate_id="cert-existing-1",
        user_id=10,
        attachment_url="https://cdn.example.com/banners/certificates/original.pdf",
        is_revoked=False,
    )
    existing_revoked = ExistingCertificate(
        certificate_id="cert-revoked-2",
        user_id=20,
        attachment_url="",
        is_revoked=True,
    )
    subs = [_submission(1, 10), _submission(2, 20), _submission(3, 30)]
    assigned = {10: [_review()], 20: [_review()], 30: [_review()]}
    received = {1: [_review()], 2: [_review()], 3: [_review()]}

    adapter = FakeCertificateAdapter(existing={10: existing_issued, 20: existing_revoked})

    preview_1 = evaluate_attempt_certificates(
        _project(),
        submissions=subs,
        assigned_by_user=assigned,
        received_by_submission=received,
        criteria=CRITERIA,
        passing_score=8,
        existing_by_user=adapter.credentials,
    )
    assert preview_1.eligible_count == 3
    assert preview_1.already_issued_count == 1
    assert preview_1.revoked_count == 1
    assert preview_1.missing_count == 1

    result_1 = generate_missing_attempt_certificates(preview_1, adapter)
    assert result_1.created_count == 1
    assert result_1.skipped_issued_count == 1
    assert result_1.skipped_revoked_count == 1
    assert result_1.failed_count == 0
    assert adapter.credentials[10].attachment_url == (
        "https://cdn.example.com/banners/certificates/original.pdf"
    )
    assert adapter.credentials[20].is_revoked is True
    assert adapter.credentials[20].attachment_url == ""
    assert adapter.credentials[30].attachment_url.startswith("https://cdn.example.com/")
    published_url_30 = adapter.credentials[30].attachment_url

    # Second click: nothing missing, zero renders, published URLs and revoked status preserved.
    preview_2 = evaluate_attempt_certificates(
        _project(),
        submissions=subs,
        assigned_by_user=assigned,
        received_by_submission=received,
        criteria=CRITERIA,
        passing_score=8,
        existing_by_user=adapter.credentials,
    )
    assert preview_2.missing_count == 0
    assert preview_2.already_issued_count == 2
    assert preview_2.revoked_count == 1

    result_2 = generate_missing_attempt_certificates(preview_2, adapter)
    assert result_2.created_count == 0
    assert result_2.retried_count == 0
    assert result_2.skipped_issued_count == 2
    assert result_2.skipped_revoked_count == 1
    assert len(adapter.render_calls) == 1
    assert adapter.credentials[30].attachment_url == published_url_30
    assert adapter.credentials[20].is_revoked is True


def test_render_failure_preserves_credential_and_retry_completes_without_reissuing():
    subs = [_submission(1, 10), _submission(2, 20)]
    assigned = {10: [_review()], 20: [_review()]}
    received = {1: [_review()], 2: [_review()]}

    adapter = FakeCertificateAdapter(fail_users={20})
    preview_1 = evaluate_attempt_certificates(
        _project(),
        submissions=subs,
        assigned_by_user=assigned,
        received_by_submission=received,
        criteria=CRITERIA,
        passing_score=8,
        existing_by_user=adapter.credentials,
    )
    result_1 = generate_missing_attempt_certificates(preview_1, adapter)
    assert result_1.created_count == 1
    assert result_1.failed_count == 1
    reserved_cert_20 = adapter.credentials[20]
    assert reserved_cert_20.attachment_url == ""
    assert reserved_cert_20.status == CertificateStatus.PENDING_RENDER

    # Preview now sees user 20 as pending retry (still in missing_count).
    preview_2 = evaluate_attempt_certificates(
        _project(),
        submissions=subs,
        assigned_by_user=assigned,
        received_by_submission=received,
        criteria=CRITERIA,
        passing_score=8,
        existing_by_user=adapter.credentials,
    )
    assert preview_2.already_issued_count == 1
    assert preview_2.pending_retry_count == 1
    assert preview_2.missing_new_count == 0
    assert preview_2.missing_count == 1

    # Clear failure and retry: same certificate_id is completed without reissuing.
    adapter.fail_users.clear()
    result_2 = generate_missing_attempt_certificates(preview_2, adapter)
    assert result_2.created_count == 0
    assert result_2.retried_count == 1
    assert result_2.skipped_issued_count == 1
    assert result_2.failed_count == 0
    assert adapter.credentials[20].certificate_id == reserved_cert_20.certificate_id
    assert adapter.credentials[20].attachment_url.endswith(
        f"/{reserved_cert_20.certificate_id}.pdf"
    )


def test_mismatched_credential_user_and_invalid_provider_url_are_rejected():
    subs = [_submission(1, 10), _submission(2, 20)]
    assigned = {10: [_review()], 20: [_review()]}
    received = {1: [_review()], 2: [_review()]}

    # Preview rejects mismatched existing credential immediately.
    with pytest.raises(ValueError, match="user_id"):
        evaluate_attempt_certificates(
            _project(),
            submissions=subs,
            assigned_by_user=assigned,
            received_by_submission=received,
            criteria=CRITERIA,
            passing_score=8,
            existing_by_user={
                10: ExistingCertificate(certificate_id="c1", user_id=999, attachment_url="")
            },
        )

    adapter = FakeCertificateAdapter(
        mismatch_user=10,
        return_url_override={20: "javascript:alert(1)"},
    )
    preview = evaluate_attempt_certificates(
        _project(),
        submissions=subs,
        assigned_by_user=assigned,
        received_by_submission=received,
        criteria=CRITERIA,
        passing_score=8,
    )
    result = generate_missing_attempt_certificates(preview, adapter)
    assert result.failed_count == 2
    assert result.created_count == 0
    assert adapter.persist_calls == []


def test_concurrent_clicks_do_not_duplicate_or_overwrite():
    subs = [_submission(1, 10), _submission(2, 20)]
    assigned = {10: [_review()], 20: [_review()]}
    received = {1: [_review()], 2: [_review()]}
    adapter = FakeCertificateAdapter(render_delay=0.05, use_locks=True)

    preview = evaluate_attempt_certificates(
        _project(),
        submissions=subs,
        assigned_by_user=assigned,
        received_by_submission=received,
        criteria=CRITERIA,
        passing_score=8,
    )

    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(generate_missing_attempt_certificates(preview, adapter))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(r.created_count for r in results) == 2
    assert sum(r.skipped_in_progress_count + r.skipped_issued_count for r in results) == 2
    assert sum(r.failed_count for r in results) == 0
    assert len(adapter.render_calls) == 2
    assert len(adapter.persist_calls) == 2


def test_private_preview_returns_bytes_without_issuing_or_publishing():
    adapter = FakeCertificateAdapter()
    rendered_payloads = []

    def fake_preview_renderer(context):
        rendered_payloads.append(context)
        return PrivatePreviewArtifact(
            content=b"%PDF-1.4 sample preview",
            content_type="application/pdf",
            filename="sample.pdf",
        )

    artifact = render_private_certificate_preview(
        fake_preview_renderer,
        {"name": "Sample Graduate", "course_name": "AI Engineering Buildcamp"},
    )
    assert artifact.content.startswith(b"%PDF-1.4")
    assert artifact.content_type == "application/pdf"
    assert len(rendered_payloads) == 1
    assert adapter.credentials == {}
    assert adapter.reserve_calls == []
    assert adapter.persist_calls == []
