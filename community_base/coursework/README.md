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
lands before `due_at`) and from the expiry sweep (`pooling.expire_pooled_reviews`, every 15
minutes). Idempotent, guarded by `PeerReviewBatch.scored_at` and a row lock, so the two triggers
racing on the same batch is safe.

A volunteer/optional review (`add_volunteer_peer_review`) is never part of a batch
(`PeerReview.batch` stays null) in either mode, matching deadline mode's existing behaviour: it
stays open regardless of the project's or batch's state.

### Expiry: what happens to both parties when a pooled window closes

No silent stall, and no reassignment (that just relocates the same indefinite-wait risk to a
different reviewer). `pooling.expire_pooled_reviews` (`coursework.expire_pooled_reviews`, every 15
minutes) finds `TO_REVIEW` reviews whose batch is past `due_at` and not yet scored:

- The reviewer who did not deliver: their review moves to `EXPIRED`, excluded from then on from
  the reviewee's score; they get a `coursework.review_window_expired` email. It can still cost
  them their own pass, through the existing `reviewed_enough_peers` mechanism (reviews *they*
  failed to give), not a new punitive field.
- The learner waiting on them: the moment their batch has no `TO_REVIEW` reviews left (every one
  `SUBMITTED` or `EXPIRED`), `try_score_batch` scores it on whatever arrived -- the existing
  median-of-available-reviews fallback (`review.calculate_median_score`), not a new scoring path.
  Never blocked longer than `Project.pooled_review_window_days` past assignment.

A late submission is accepted, and counts, until its batch is scored (`submit_peer_review` rejects
it only once `PeerReviewBatch.scored_at` is set -- `review.ReviewWindowClosedError`).

## Read paths

`review.review_accepts_submission(review, project)` is the one place that decides whether a
specific review can still be filled in from the learner-facing eval form: for deadline mode it is
the same expression every caller used before this changed (`project.state == PEER_REVIEWING`); for
pooled mode it checks the review's own batch (or, for a volunteer review with no batch, is always
open).

## Notifications

`community_base/coursework/notifications.py` covers the four event-driven purposes, each a plain
function call at the moment of the event (not a scheduled scan), reusing `mail.send`'s own
idempotency key like `reminders.py` already does -- no parallel send mechanism:

| Purpose | Fires when | Recipient |
|---|---|---|
| `coursework.review_assigned` | A reviewer is assigned one or more reviews (deadline-mode whole-project assignment or one pooled batch); one email per reviewer per event, not one per review row | Reviewer |
| `coursework.pool_ready` | A pooled batch forms | Every batch member |
| `coursework.review_received` | A review is submitted (both modes) | Reviewee |
| `coursework.review_window_expired` | A pooled review's batch expires it | Reviewer |

`reminders.py`'s existing `coursework.peer_review_deadline` scheduled reminder now also scans
pooled reviews approaching their batch's `due_at` (`pooled_reviews_due_between`), reusing the same
purpose and idempotency-key shape rather than a parallel "expiry approaching" job.

## Certificates

The package has no automatic issuance and never did -- `certificates.issue_certificate` has always
been staff/API-key-triggered only (Studio, `curriculum/api_views.py`). "Certificate on request" is
a package feature addition, not a behaviour change within the package; AISL's own local automatic
issuance (`content/services/peer_review_service.py`) retires separately in A5.1.

`certificates.certificate_eligibility(enrollment)` returns `CertificateEligibility(eligible,
reasons)`, mode-agnostic (identical for a dated cohort or a pooled project): every countable unit
of the enrollment's course completed (`Course.total_units`/`completed_units`, already excluding
bonus content), and at least `cohort.min_projects_to_pass` of the enrollment's project submissions
`passed` -- which already requires both a passing project score and the learner's own
`reviewed_enough_peers`, so no separate review-completion check is needed.

`certificates.request_certificate(enrollment)` checks eligibility and, if it passes, calls the
site's certificate generator and issues. Re-requesting for an enrollment that already has a
certificate re-generates and re-attaches the artifact rather than refusing as "already issued" --
the recommended, reversible default for learners grandfathered from AISL's prior automatic
issuance (open question in DataTalksClub/community-base#256; not decided unilaterally, and easy to
change since nothing here treats "already issued" as terminal). Exposed as
`POST /api/v1/courses/<course_slug>/cohorts/<cohort_slug>/certificate-request`
(session-authenticated) and as an eligibility column on the Studio certificates page.

Artifact generation is a site-supplied seam, `COURSEWORK_CERTIFICATE_GENERATOR`, following
`community_base.events`'s `EVENT_BANNER_GENERATOR` pattern exactly rather than inventing a second
configuration mechanism (`community_base/coursework/integrations.py`): a dotted path to a site
callable that returns a plain URL string, resolved through `kernel.hooks`. The package never sees
an endpoint or a token -- a site's callable owns those entirely (AISL:
`BANNER_GENERATOR_FUNCTION_URL`/`BANNER_GENERATOR_AUTH_TOKEN` through its own `IntegrationSetting`).
Raises `ImproperlyConfigured` when unset, since a learner-triggered request with nothing configured
to generate an artifact is an operator error worth surfacing loudly (`events.process_recording`'s
precedent), unlike `generate_banner`'s silent `None`. Whether the artifact is a PDF, an image, or a
page offering both is a site decision this seam deliberately does not fix (also open in #256):
`Certificate.url` holds whichever URL comes back either way, so nothing here needs to change once
that is answered.
