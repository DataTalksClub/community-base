# Homework steps

Install `community_base.homework_steps` beside `community_base.curriculum` and run its migration.
The app does not require `community_base.coursework`, and `HomeworkDraft` has no foreign key to an
assignment, cohort or submission table. The host controls its public route and page template.

The site resolves the assignment from its own route and access rules. It passes an `Assignment`
from `community_base.homework_steps.types` to `handle_stepper(request, assignment, adapter, ...)`.
`Assignment.key` must be opaque, stable and cohort-qualified when a homework unit is reused.
Never derive that key from a query string or submitted form field. Question and option keys must
also be stable across content re-imports and display-order changes.

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
