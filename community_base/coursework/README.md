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
default 7 days, configurable per project). `pooling.form_pooled_batches(project)` repeats it until
fewer than `n + 1` submissions wait, so one trigger forms every batch a backlog allows: 8 waiting
submissions with `n = 3` form two batches. It runs after commit from `projects.submit_project`,
and the `coursework.form_pooled_batches` job (every 15 minutes) runs it for every open pooled
project, forming any batch the submit-time callback missed (an import, a backfill, a failed
`on_commit`).

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

## Course page project rows

`project_rows.project_row(project, submission, completed_reviews=..., review_due_at=None)` returns
one learner's row in a course page Projects table: stage, badge label, CMP badge class, pill
surface, score, link target and the deadline to show. It is the course management platform's
learner-facing presentation, moved here unchanged (C5.2k, community-base#312); do not redesign the
labels here.

| State | Not submitted | Submitted | Link |
|---|---|---|---|
| `CL` | Closed | Closed | none |
| `CS` | Open | Submitted | `submit` |
| `PR` | Not submitted | Review, then Review completed | `eval` |
| `CO` | Not submitted | Passed ({score}) or Failed ({score}) | `results` |

- Review completed: the learner's non-optional reviews of others in state `SU` reach
  `Project.number_of_peers_to_evaluate`. Optional, `TR` and `EX` reviews do not count.
- Pill surfaces: `past` (closed, never submitted, failed), `your_move` (open, reviews owed),
  `done` (submitted, reviews delivered), `result` (passed). A site maps each to its own style.
- Deadline: the review due date while reviewing a submitted project and once completed (with
  `completed` set, where CMP shows "Completed"), otherwise the submission due date.
- Pooled projects: `Project.state` is only `CS` or `CL`, so a submitted learner's stage comes from
  `ProjectSubmission.review_state` (`AW` as `CS`, `IR` as `PR`, `SC` as `CO`) and the review
  deadline is their batch `due_at`. A self-paced learner has no submission deadline: the row's
  `deadline` and `deadline_kind` are `None` until they are in a batch, and the include then
  renders no deadline line. A closed project reads Closed in both modes.

`project_rows_for_cohort(cohort, user, url_for=None)` builds every row of a cohort in two queries.
`url_for(project, link_target)` is the site's route resolver and sets `row.href`. The overridable
`coursework/_project_row.html` include renders one row as a `cb-card` list item, exposing the
surface, stage and deadline kind as data attributes.

`project_row` reads attributes only, so a site still on its own project rows with the same state
codes can call it before adopting the package models.

## Project placement and submission fields

`Project.module` optionally places a project in a cohort module (`SET_NULL`, reverse
`module.projects`), mirroring `Homework.module`, so a site can show a project with its module.
Deleting the module keeps the project.

`Project.commit_id_field` (default `True`) decides whether a submission needs a commit id. On, the
package form shows the input and `ProjectSubmission.clean` requires a value, so `submit_project`
rejects a blank one (CMP and DTC behaviour). Off, the form asks only for the repository link and
`submit_project` stores an empty commit id, ignoring any value passed in.

## The shared project submission form

`coursework/_project_submission_form.html` is the one project submission form for every site, ported
from CMP's "Submission details". It renders, in order: GitHub link to the project (required), commit
ID with a "Where do I find the commit ID?" disclosure (when `Project.commit_id_field`), learning in
public links ("Add up to N", `+ Add link`, optional; hidden when the cap is `0` or the enrollment
opted out), time spent on project in hours (when `time_spent_project_field`), any host-added fields,
certificate name (when enabled), and a status line: "Status: Not saved yet" or "Last saved at", with
"save now, update before the deadline" while editable. Each field has a help disclosure
(`.cb-form-help`). The FAQ contribution field is not part of the shared form; the `faq_*` columns
are kept and preserved on save (retirement is C5.2o).

Validation (`ProjectSubmissionForm`): the link is an http(s) GitHub repository URL
(`github_hosts`; a subclass sets `None` to accept any public host); the commit ID is 7 to 40
hexadecimal characters, trimmed; learning in public links are stripped, de-duplicated, capped at
`learning_in_public_cap_project` and must be public http(s) URLs; hours are a number of at least
zero. Edits are allowed while the project collects submissions and before `submission_due_date`,
and locked after it (`projects.submission_editable`); a pooled submission also locks once it joins
a review batch.

Certificate name: `COMMUNITY_BASE["COURSEWORK_PROJECT_CERTIFICATE_NAME_FIELD"]` (default `True`,
CMP parity) sets the site default; `certificate_name_field=True/False` on the form overrides it per
course. A non-blank value is saved to `Enrollment.certificate_name`. AISL sets the key to `False`.

Embedding. The host resolves the project and enrollment through its own access rules, renders the
partial inside its own unit page, and posts back to its own view:

```python
from community_base.coursework.project_submission_flow import (
    build_project_submission_form,
    process_project_submission,
)

def project_unit(request, ...):
    project, enrollment = ...  # host access rules
    if request.method == "POST":
        outcome = process_project_submission(request, project, enrollment, action_url=unit_url)
        if outcome.succeeded:  # "saved" or "deleted"
            return redirect(unit_url)
        project_form = outcome.form  # "invalid", "closed" or "anonymous", with errors
    else:
        project_form = build_project_submission_form(
            project, user=request.user, enrollment=enrollment, action_url=unit_url
        )
    return render(request, "site/unit.html", {"project_form": project_form, ...})
```

```django
{% include "coursework/_project_submission_form.html" with project_form=project_form %}
```

`process_project_submission` never adds messages or redirects; `outcome.action` is `saved`,
`deleted`, `invalid`, `closed` or `anonymous`. After commit it fires `COURSEWORK_PROJECT_SUBMITTED`
(`submission`, `created`) or `COURSEWORK_PROJECT_DELETED` (`project`, `user`), where a site sends
its confirmation mail. The package `coursework_project` page uses the same form and handler.

Styling hooks: the partial uses structural `cb-` classes (`cb-section`, `cb-field`, `cb-label`,
`cb-input`, `cb-form-help`, `cb-disclosure`, `cb-form-error`, `cb-form-status`, `cb-form-actions`)
and `data-project-*` attributes, and no site CSS. A site may also override the template by name.
`community_base/coursework_project_form.js` adds `+ Add link` and the Remove confirmation; without
JavaScript the form still posts the saved links plus one blank slot.

Extension point: subclass the form, declare fields, and write them in `apply_extra_fields`, which
runs inside `submit_project`'s transaction before `full_clean` (model errors land on the form). The
partial renders extra fields after "Time spent", or includes the subclass's `extra_fields_template`
(which receives `project_form`). Pass the subclass as `form_class=` to both helpers.

```python
class FaqProjectSubmissionForm(ProjectSubmissionForm):
    faq_contribution_url = forms.URLField(label="FAQ contribution PR or issue URL", required=False)

    def clean_faq_contribution_url(self):
        url = self.cleaned_data["faq_contribution_url"]
        return url  # plus the site's own rule

    def apply_extra_fields(self, submission):
        submission.faq_contribution_url = self.cleaned_data["faq_contribution_url"]
```

## Installing without the package Studio and member API

`CourseworkConfig.ready()` registers two site-facing surfaces unless a site turns them off:

| `COMMUNITY_BASE` key | Default | Off means |
|---|---|---|
| `COURSEWORK_STUDIO_ENABLED` | `True` | No coursework Studio section is registered. The Studio views import `community_base.accounts`, so a site that owns its own user app and Studio turns this off. |
| `COURSEWORK_MEMBER_API_ENABLED` | `True` | `api_views` is not imported, so the leaderboard, certificate-request and enrollment-preference member routes are not registered. |

The job handlers (`pooling`, `reminders`) always register. A site that keeps its own learner
routes and Studio (AISL) sets both keys to `False` and calls the package services directly. The
gate does not key on `community_base.accounts` being installed, because DTC does not install it and
keeps both surfaces. These are startup settings read once in `ready()`, not runtime config keys.

## Notifications

`community_base/coursework/notifications.py` covers the four event-driven purposes, each a plain
function call at the moment of the event (not a scheduled scan), reusing `mail.send`'s own
idempotency key like `reminders.py` already does -- no parallel send mechanism:

| Purpose | Fires when | Recipient |
|---|---|---|
| `coursework.review_assigned` | A reviewer is assigned one or more reviews by deadline-mode whole-project assignment; one email per reviewer per event, not one per review row | Reviewer |
| `coursework.pool_ready` | A pooled batch forms; the only email a batch member gets for it | Every batch member |

A pooled batch of `n + 1` sends exactly `n + 1` emails. Every member is also a reviewer, so
`pool_ready` is the review request: its context carries `review_count`, `due_date` (the batch
`due_at`), `reviews` (one `{number, review_id, url}` per assigned review) and `review_list_url`.
Links come from the `COURSEWORK_REVIEW_URL_BUILDER` hook, called as
`builder(project=..., review=...)` (`review=None` for the project's review page). The default
reverses the package routes `coursework_projects_eval_submit` and `coursework_projects_eval`
against `SITE_URL`, and returns `None` on a site that does not mount `coursework.urls`; such a site
points the hook at its own routes.
| `coursework.review_received` | A review is submitted (both modes) | Reviewee |
| `coursework.review_window_expired` | A pooled review's batch expires it | Reviewer |

A self-paced cohort has no deadlines, so the homework and project-submission deadline reminders
skip it even when a date is stored. `reminders.py`'s existing `coursework.peer_review_deadline` scheduled reminder now also scans
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

## Homework from a content repository

A cohort binds its gradable assignments in `cohort.yaml` (`FORMAT.md` section 3.8):

```yaml
homework:
  - module: core
    source: homework/core/homework.yaml
    unit: 9a2b3c4d-0003-4000-8000-000000000002
```

`community_base.coursework.manifests` reads the manifests those bindings name and
`community_base.coursework.importing` writes the rows. Both run inside the one course sync, from
the read the course parser already did, so nothing here walks a repository, parses YAML or
validates a key; the document toolkit and the kind registry did all of that before this app was
called. What the reader owns is the binding half that no single file states:

- the manifest a binding points at, resolved against the cohort directory and never outside it;
- whether the cohort actually places the top-level module the binding names;
- whether the binding's `unit` is a `kind: homework` unit of this course;
- whether each sealed answer was encrypted for this course, this homework and this question.

Each of those is an error naming the file, the YAML pointer and rule `3.8`, the same shape a
toolkit diagnostic has.

The other binding form selects a course-tree homework Unit by its `content_id`:

```yaml
homework:
  - module: core
    unit: 9a2b3c4d-0003-4000-8000-000000000009
    due_at: 2026-10-09T23:00:00+00:00
    form:
      learning_in_public_cap: 7
```

Its YAML and sole `homework.md` companion define one curriculum Unit. Every explicit cohort
binding materializes a separate Homework with its own questions and learner submissions. The
reader validates all authored YAML questions, including unbound prose Units, before the course
import writes anything. Cohort manifest and course-tree assignments share one retained set for
cleanup, so removing one binding does not delete another cohort's assignment or the other source
form. A changed source path or containing module matches Unit, Homework and Question by stable
identity before slug fallback and retains their learner records.

The source `due_at` and individual `form` fields are inherited unless a binding explicitly
overrides them. An omitted binding date keeps the source date; `due_at: null` explicitly clears it
for a self-paced assignment. Live assignments need a resulting date. Source or binding due/form
edits update the assignment on re-import. `initial_state` is create-only; an operator's later
open/scored state is preserved. These rules keep cohort policy separate from source metadata.

Question order follows the authored YAML list through additive `Question.authored_position`.
Legacy rows with null positions keep their database ID order. In a hybrid assignment, authored
questions appear first and null-position questions follow by ID on every supported database.

Authored `stepper: true` enables the existing stepper for that source assignment; omitted or
`false` keeps the legacy descriptor output. Question `step_label` is source-owned navigation
metadata. The built-in final fields follow `form.homework_url`, `form.time_spent_lectures` and
`form.time_spent_homework`; they read and write the existing `Submission` columns through
`submit_homework`. A positive `learning_in_public_cap` adds the optional public-links question,
validated and scored by the existing submission/scoring path. The accepted snapshot is rebuilt
from the same columns. The cohort binding may override individual form settings. Arbitrary
`final_fields` keys are rejected by the source schema.

### Answers in the two source forms

A cohort manifest question carries the envelope of `answer_crypto.py`, never a plaintext answer. The
importer holds no key: it calls `answer_crypto.validate_source_envelope`, which runs the check
`decrypt_answer` runs before it touches a key (the envelope's fields, and that its context binds
this course, this homework and this question), and then stores the envelope verbatim in
`Question.answer_envelope`. `Question.correct_answer`, the plaintext column, is cleared on every
imported row, so a repository-managed answer has one representation and one decryption boundary,
`answer_resolution.resolve_correct_answer`. A plaintext `correct:` key in a manifest is rejected by
the registry as an unknown key, before this app runs.

The distinct course-tree YAML schema accepts a quoted `correct` string. One-based choice indices
are checked against the ordered options; free-form numeric answers are checked for valid finite
numbers. The original string is stored losslessly in `Question.correct_answer`, and
`answer_resolution.resolve_correct_answer` supplies the same scoring service used by envelope
answers. Ordinary homework pages, curriculum projections and stepper Question/Option descriptors
exclude correct answers. `homework_reveal` alone controls their display after an authorized
submission: immediately for self-paced work, or after an operator marks a dated assignment
scored.

A choice question (`multiple_choice`, `checkboxes`) carries `options` as `{id, label}` pairs and no
`answer_type`; a free-form question carries an `answer_type` and no options. `answer_type: any` is
not scored and carries no answer; every other answer type carries one.

### What a re-import does and does not touch

Re-import is idempotent: rows are matched on `content_id` first and on their slug or stable id
second, written only when a value changed, and removed when neither source form retains them.
One field is deliberately not restored:

- `initial_state` is the state a homework is created in. An operator opens and scores a homework
  after the import, and a second sync must not close it again.

`Homework.module` and `Homework.unit` follow the binding; both are null for a Studio-authored
homework, which belongs to no module tree.

### Self-paced homework: scored and revealed on submit

`Homework.reveals_on_submit` is true for a self-paced cohort's homework, derived from
`Cohort.mode` like `Project.uses_pooled_review`. `submit_homework` already scores every submission
(`scoring.update_score` sets `Answer.is_correct` and the totals); for such a homework it also
refreshes the cohort leaderboard, so the submission counts at once without an operator scoring
pass. Because the learner then sees the answers, a second submission is rejected with reason
`already_submitted`. `homework_reveal` owns the policy: results are revealed to a learner with a
submission on submit for a self-paced homework, and only once the homework is `SCORED` for a dated
one. `homework_form_context` exposes `results_revealed` and `revealed_rows`
(`(question, answer, result)`), and the form shows correctness and the correct answer.

Due dates: `Homework.due_date`, `Project.submission_due_date` and `Project.peer_review_due_date`
are optional for a self-paced cohort and still required by model validation for a dated one. A
self-paced homework never reports `deadline_passed`.

### One form, two pages

`coursework/_homework_form.html` is the submission form, and both the homework page and a bound
unit's page include it; a unit page's form posts to the homework view, so there is one form and one
POST handler. `submissions.homework_form_context` builds what either page needs. The unit stays a
page in the reading order and the assignment stays cohort-owned: the unit page shows the cohort's
homework rather than owning one.

## Inline homework steps

Sites using package-owned `Homework`, `Question` and `Submission` rows may install the optional
`community_base.homework_steps` app and use `coursework_assignment(homework, user)` with
`CourseworkAdapter(homework)`. Its final submit calls this app's existing `submit_homework` path,
so scoring, state checks and hooks stay authoritative. See `community_base/homework_steps/README.md`.
The adapter maps `HomeworkState.OPEN`, `CLOSED` and `SCORED` into the generic assignment
availability and places the learner's `Submission.submitted_at` and answers in an
`AcceptedSubmission` snapshot. The generic descriptor also carries accepted host-defined final
fields. A scored homework with no submission by this learner is presented as
`Closed — not submitted`; scoring the assignment does not imply that every learner submitted or
received a score. On a closed/scored review, the accepted snapshot remains primary and a different
saved `HomeworkDraft` is shown separately as an unsubmitted draft. The generic state and shared
fragment are documented in `community_base/homework_steps/README.md`. For a self-paced homework the
adapter reports a learner who has submitted as `scored`, refuses further writes, and supplies
`Assignment.question_results` from `homework_reveal`; for a dated homework it supplies them only
after scoring.
