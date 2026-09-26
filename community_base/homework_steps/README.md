# Homework steps

Install `community_base.homework_steps` beside `community_base.curriculum` and run its migration.
The app does not require `community_base.coursework`, and `HomeworkDraft` has no foreign key to an
assignment, cohort or submission table. The host controls its public route and page template.

The site resolves the assignment from its own route and access rules. It passes an `Assignment`
from `community_base.homework_steps.types` to `handle_stepper(request, assignment, adapter, ...)`.
`Assignment.key` must be opaque, stable and cohort-qualified when a homework unit is reused.
Never derive that key from a query string or submitted form field. Question and option keys must
also be stable across content re-imports and display-order changes.

Set `Question.step_label` for a semantic navigation label such as `Learning in Public`; the default
remains `Question N`. Set `Assignment.availability` to `open`, `closed` or `scored`; it defaults to
`open` for existing adapters. Pass an `AcceptedSubmission` with the accepted answers, final fields
and `submitted_at` when one exists:

```python
from community_base.homework_steps.types import AcceptedSubmission

assignment = Assignment(
    key=assignment_key,
    title=homework.title,
    questions=questions,
    availability="closed",
    accepted_submission=AcceptedSubmission(
        answers=accepted_answers,
        final_fields=accepted_fields,
        submitted_at=submission.submitted_at,
    ),
)
```

`has_submission`, `existing_answers`, `existing_final_fields`, and
`Assignment.context["homework_is_submitted"]` remain supported for v0.5.10 adapters. The explicit
snapshot takes precedence when provided. Accepted snapshots and `HomeworkDraft` rows remain
separate: draft existence or revision alone never means that there are unsent changes. The package
normalizes every declared question and final field, including blanks, before comparing snapshots;
checkbox answer ordering does not affect the comparison.

`homework_state_for(user, assignment)` reads only that learner's existing draft. It is suitable for
a host-owned navigation row; it never creates a draft. For a signed-in request, the host can pass
the result through to the same package fragment used by the shared page:

```python
from community_base.homework_steps.state import homework_state_for

homework_state = homework_state_for(request.user, assignment)
```

The returned `LearnerHomeworkState` exposes `value`, `label`, `aria_label`, `availability`,
`has_submission`, `has_saved_draft`, `has_pending_changes` and `submitted_at`.

```django
{% include "homework_steps/_state_label.html" with homework_state=homework_state %}
```

The fragment exposes a stable `data-homework-state` value and an accessible label. The shared
stepper uses the same fragment and state object. Hosts place it next to the homework title in
navigation and near the due line on the homework page. The labels are `Not submitted`, `Draft`,
`Submitted`, `Unsubmitted changes`, `Closed — not submitted`, and `Scored`. Scored status requires
an accepted learner submission; a scored assignment without one stays `Closed — not submitted`.
For a closed or scored assignment, Review shows the accepted snapshot and its time first. A saved
draft that differs from it appears separately as `Unsubmitted draft`; the review does not expose a
submit control. An open accepted submission with changed answers is `Unsubmitted changes`.

`stepper.review_rows` keeps its existing `(prompt, answer, url)` tuples for site-owned templates;
the shared partial uses `stepper.review_display_rows`, which also carries semantic labels and
question numbers.

```python
return handle_stepper(
    request,
    assignment,
    adapter,
    action=request.path,
    template_name="my_site/homework_unit.html",
    step_param="homework_step",
    query_params={"cohort": cohort.slug},
)
```

The page template includes `homework_steps/_stepper.html`, or overrides that partial. The handler
merges `Assignment.context` into the page context and adds `stepper`. Plain POST navigation works
without JavaScript. JavaScript saves on input; a site can expose a dedicated AJAX endpoint using
`save_answer(user, assignment, question_key=..., answer=..., revision=...)` after independently
resolving and authorizing the assignment. Put per-question AJAX URLs in
`Assignment.context["homework_save_urls"]`; the script expects JSON with `revision` and `saved`.
On a successful legacy form submission, call `clear_draft(user, assignment.key)` so old step
answers cannot reappear.

The default `step_param` continues to read and generate query-step URLs for existing bookmarks. A
host can add canonical route-step URLs by passing the route's step value as `route_step` and a
`step_url_builder` that maps a step key to a path, for example `/homework/intro`. The handler uses
that builder for navigation, form actions and redirects, while still accepting old query-step URLs
when `route_step` is absent. `query_params` are appended to builder paths so cohort context is kept.

`Adapter.eligibility(request, assignment)` returns `Eligibility(read, write, submit, reason)`.
The handler checks this on every request, including final submission. The adapter's
`submit(request, assignment, answers, final_fields)` receives the complete latest draft. It must
call the host's existing deadline, access, scoring, notification and resubmission path, returning
a success object or an `HttpResponse`. It returns `None` or raises `ValidationError` on refusal.
The package deletes the draft only after success. An adapter should recheck its own policy in its
submission path, because it remains the authority for the submission.

`Question.type` is `choice`, `checkbox`, `short_text` or `long_text`. Choice answers are one stable
option key, checkbox answers are lists of stable option keys, and text answers are strings.
`FinalField.type` is `text`, `url` or `textarea`. The app caps answers at 10,000 characters each,
the draft payload at 64 kB, and uses a revision precondition on each save to reject stale tabs.
Forms carry `stepper.draft_token` in a hidden `draft_token` field. The token changes when a draft
is cleared after submission, so retrying the old final POST cannot submit again. Dedicated AJAX
routes can pass `token=request.POST["draft_token"]` to `save_answer` for the same protection.
An empty choice answer and empty checkbox selection clear the previous answer. Existing submitted
answers prefill a new draft, so an edit can pass the full answer set to a replacement-style host
submission service.

The stock `coursework_assignment(homework, user)` and `CourseworkAdapter(homework)` are in
`community_base.homework_steps.coursework`. They import package coursework only when used and
delegate final submission to `community_base.coursework.submissions.submit_homework`. Sites still
using site-owned assessment rows supply their own adapters. Public chrome and styling stay with
the site.
