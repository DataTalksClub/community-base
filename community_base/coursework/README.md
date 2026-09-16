# Coursework

Use `community_base.coursework` for homework, projects, peer review, leaderboards, certificates
and Wrapped statistics. It builds on `community_base.curriculum` (`Course`, `Cohort`,
`Enrollment`, `Certificate`) and has no imports from either website.

## Assessment modes

A project's peer-review assignment strategy is derived from its cohort's `Cohort.mode`
(`Project.uses_pooled_review`), not a separate field:

- `cohort` (dated): deadline-driven. An operator calls `review.assign_peer_reviews_for_project`
  once submissions close, which assigns the full review graph and moves `Project.state` through
  `COLLECTING_SUBMISSIONS -> PEER_REVIEWING`; `review.score_project` scores everyone and moves it
  to `COMPLETED`. One project-wide lifecycle, because a dated cohort's submissions genuinely move
  through the same phase together.

- `self_paced` (pooled): submissions accumulate continuously; there is no cohort-wide moment to
  hang a phase on, so `Project.state` narrows to a binary open/closed switch for a pooled project
  (`COLLECTING_SUBMISSIONS` until an operator sets `CLOSED`; `PEER_REVIEWING`/`COMPLETED` are
  never set and both whole-project functions above refuse to run against one). Progress instead
  lives on `PeerReviewBatch` and on the per-submission `ProjectSubmission.review_state`
  (`AWAITING_ASSIGNMENT` / `IN_REVIEW` / `SCORED`), maintained by `community_base.coursework.pooling`.

`review_state` is maintained for *both* modes (deadline mode mirrors it in bulk at the same
moments it flips `Project.state`, in `review.set_review_state_for_project`), so every reader that
needs "is this submission's peer review finished" -- `leaderboard.completed_project_submissions_prefetch`,
`statistics.calculate_project_statistics` -- reads `review_state`, not `Project.state`, and works
identically across both modes.

### Pooled batches

`pooling.try_form_batch(project)` takes the oldest `number_of_peers_to_evaluate + 1` waiting
submissions once that many have accumulated, and assigns a full round-robin review graph over
them as one `PeerReviewBatch` (`formed_at`, `due_at = formed_at + Project.pooled_review_window_days`,
default 7 days, configurable per project). Dispatched after commit from `projects.submit_project`.

The batch, not the individual submission, is the scoring unit -- see `PeerReviewBatch`'s
docstring for why scoring a submission the moment its own incoming reviews land is wrong (its
owner's *outgoing* reviews, an independent set within the same batch, may still be pending).
`pooling.try_score_batch(batch)` scores every member once every review in the batch is resolved
(`SUBMITTED` or `EXPIRED`), called from the happy path (`review.submit_peer_review`, every review
lands before `due_at`) and from the expiry sweep (`pooling.expire_pooled_reviews`, coming in the
C5.2g issue). Idempotent, guarded by `PeerReviewBatch.scored_at` and a row lock, so the two
triggers racing on the same batch is safe.

A volunteer/optional review (`add_volunteer_peer_review`) is never part of a batch
(`PeerReview.batch` stays null) in either mode, matching deadline mode's existing behaviour: it
stays open regardless of the project's or batch's state.

## Read paths

`review.review_accepts_submission(review, project)` is the one place that decides whether a
specific review can still be filled in from the learner-facing eval form: for deadline mode it is
the same expression every caller used before this changed (`project.state == PEER_REVIEWING`); for
pooled mode it checks the review's own batch (or, for a volunteer review with no batch, is always
open).

## Notifications and certificates

Peer review email notifications (assignment, pool-ready, expiry-approaching, review-received) and
certificate eligibility, request-based issuance and the banner-generator artifact seam
(`COURSEWORK_CERTIFICATE_GENERATOR`, following the `EVENT_BANNER_GENERATOR` pattern in
`community_base.events`) are covered in the C5.2g and C5.2h issues respectively
(`docs/plan/phase-5.md`).
