"""Shared GET, save and submit handler embedded by a site-owned route."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.core import signing
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render

from community_base.homework_steps.models import HomeworkDraft
from community_base.homework_steps.services import (
    DraftConflict,
    get_or_seed_draft,
    save_answer,
    save_final_fields,
    submit_draft,
    validate_assignment,
)


def _step(assignment, key):
    if key == "intro":
        return "intro", None, "review" if not assignment.questions else assignment.questions[0].key
    if key == "review":
        return assignment.questions[-1].key, None, "review"
    keys = [question.key for question in assignment.questions]
    if key not in keys:
        raise ValueError("Unknown step")
    index = keys.index(key)
    return (
        "intro" if index == 0 else keys[index - 1],
        assignment.questions[index],
        "review" if index == len(keys) - 1 else keys[index + 1],
    )


def _answer_from_post(request, question):
    if question.type == "checkbox":
        return request.POST.getlist("answer")
    return request.POST.get("answer", "")


def _final_fields_from_post(request, assignment):
    return {
        field.key: request.POST.get(f"final_{field.key}", "") for field in assignment.final_fields
    }


def _append_query(url, params):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment)
    )


def _step_url(action, query_params, step_param, step, step_url_builder=None):
    if step_url_builder is None:
        url = action
        params = {**query_params, step_param: step}
    else:
        url = step_url_builder(step)
        params = query_params
    return _append_query(url, params)


def _has_submission(assignment, context):
    return assignment.has_submission or bool(context.get("homework_is_submitted"))


def _has_pending_changes(assignment, draft):
    question_keys = {question.key for question in assignment.questions}
    field_keys = {field.key for field in assignment.final_fields}

    def populated(values, allowed):
        return {
            key: value
            for key, value in values.items()
            if key in allowed and value not in (None, "", [])
        }

    return populated(draft.answers, question_keys) != populated(
        assignment.existing_answers, question_keys
    ) or populated(draft.final_fields, field_keys) != populated(
        assignment.existing_final_fields, field_keys
    )


def _resume_step(assignment, draft):
    for question in assignment.questions:
        if draft.answers.get(question.key) in (None, "", []):
            return question.key
    return "review"


def _valid_receipt(request, assignment):
    receipt = request.GET.get("receipt")
    if not receipt:
        return False
    try:
        payload = signing.loads(receipt, salt="homework-steps-submitted", max_age=300)
    except signing.BadSignature:
        return False
    return payload == {"user": request.user.pk, "assignment": assignment.key}


def _render(
    request,
    assignment,
    *,
    action,
    query_params,
    step_param,
    template_name,
    step,
    draft,
    eligibility,
    error="",
    status=200,
    typed_answer=None,
    typed_fields=None,
    step_url_builder=None,
):
    previous, question, next_step = _step(assignment, step)
    answer = (
        typed_answer
        if typed_answer is not None
        else (
            draft.answers.get(question.key, [] if question.type == "checkbox" else "")
            if question
            else None
        )
    )
    field_values = typed_fields if typed_fields is not None else draft.final_fields
    field_rows = [(field, field_values.get(field.key, "")) for field in assignment.final_fields]
    options = (
        [
            (option, option.key in answer if isinstance(answer, list) else option.key == answer)
            for option in question.options
        ]
        if question
        else []
    )
    action_url = _step_url(action, query_params, step_param, step, step_url_builder)
    nav_steps = [
        (
            "Introduction",
            _step_url(action, query_params, step_param, "intro", step_url_builder),
            step == "intro",
        )
    ]
    nav_steps += [
        (
            item.step_label or f"Question {index}",
            _step_url(action, query_params, step_param, item.key, step_url_builder),
            step == item.key,
        )
        for index, item in enumerate(assignment.questions, start=1)
    ]
    nav_steps.append(
        (
            "Review & submit",
            _step_url(action, query_params, step_param, "review", step_url_builder),
            step == "review",
        )
    )
    review_rows = []
    review_display_rows = []
    for item in assignment.questions:
        answer_value = draft.answers.get(item.key, "")
        if isinstance(answer_value, list):
            labels = {option.key: option.label for option in item.options}
            answer_display = ", ".join(labels.get(key, key) for key in answer_value)
        elif item.type == "choice":
            answer_display = next(
                (option.label for option in item.options if option.key == answer_value),
                answer_value,
            )
        else:
            answer_display = answer_value
        review_url = _step_url(action, query_params, step_param, item.key, step_url_builder)
        # Keep the original tuple contract for site-owned templates. The richer
        # rows give the shared partial enough data to show semantic labels.
        review_rows.append((item.prompt, answer_display, review_url))
        review_display_rows.append(
            {
                "step_label": item.step_label,
                "question_number": len(review_display_rows) + 1,
                "has_semantic_label": bool(item.step_label),
                "prompt": item.prompt,
                "answer": answer_display,
                "url": review_url,
            }
        )
    context = dict(assignment.context) if isinstance(assignment.context, dict) else {}
    save_urls = context.get("homework_save_urls", {})
    save_url = save_urls.get(question.key) if question and isinstance(save_urls, dict) else None
    save_url = save_url or context.get("homework_save_url") or action_url
    question_label = ""
    if question:
        question_number = [q.key for q in assignment.questions].index(step) + 1
        question_label = question.step_label or f"Question {question_number}"
    context.update(
        {
            "stepper": {
                "assignment": assignment,
                "action": action_url,
                "save_url": save_url,
                "step_param": step_param,
                "nav_steps": nav_steps,
                "review_rows": review_rows,
                "review_display_rows": review_display_rows,
                "step": step,
                "step_number": 0
                if step == "intro"
                else len(assignment.questions) + 1
                if step == "review"
                else [q.key for q in assignment.questions].index(step) + 1,
                "step_count": len(assignment.questions) + 2,
                "previous": previous,
                "previous_url": _step_url(
                    action, query_params, step_param, previous, step_url_builder
                ),
                "next": next_step,
                "next_url": _step_url(
                    action, query_params, step_param, next_step, step_url_builder
                ),
                "question": question,
                "question_label": question_label,
                "options": options,
                "answer": answer,
                "final_values": field_values,
                "final_field_rows": field_rows,
                "revision": draft.revision,
                "draft_token": str(draft.token),
                "saved_at": draft.saved_at,
                "draft_status": "Saved" if draft.revision else "Draft ready",
                "can_write": eligibility.write,
                "can_submit": eligibility.submit,
                "reason": eligibility.reason,
                "error": error,
                "submitted": _valid_receipt(request, assignment)
                or _has_submission(assignment, context),
                "has_pending_changes": _has_submission(assignment, context)
                and _has_pending_changes(assignment, draft),
                "notice": request.GET.get("notice") == "changed",
            }
        }
    )
    return render(request, template_name, context, status=status)


def handle_stepper(
    request,
    assignment,
    adapter,
    *,
    action=None,
    template_name="homework_steps/page.html",
    step_param="step",
    query_params=None,
    route_step=None,
    step_url_builder=None,
):
    """Handle one site-resolved homework route; site controls URL and page template.

    `assignment` must be constructed from a server lookup. Never pass a key
    selected from request.GET or request.POST into that lookup.
    """

    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    if not request.user.is_authenticated:
        return HttpResponseForbidden()
    validate_assignment(assignment)
    query_params = query_params or {}
    eligibility = adapter.eligibility(request, assignment)
    if not eligibility.read:
        return HttpResponseForbidden(eligibility.reason or "You cannot view this homework.")
    action = action or request.path
    if (
        request.method == "POST"
        and request.POST.get("assignment_key", assignment.key) != assignment.key
    ):
        return JsonResponse({"error": "Unknown assignment"}, status=400)
    if request.method == "POST":
        try:
            posted_step = request.POST.get(step_param, route_step or "intro")
            if route_step is not None and posted_step != route_step:
                return JsonResponse({"error": "Route step does not match the form."}, status=400)
            _step(assignment, route_step or posted_step)
        except ValueError:
            return JsonResponse({"error": "Unknown step"}, status=400)
    was_existing = HomeworkDraft.objects.filter(
        user=request.user, assignment_key=assignment.key
    ).exists()
    draft = get_or_seed_draft(request.user, assignment)
    if request.method == "GET":
        assignment_context = assignment.context if isinstance(assignment.context, dict) else {}
        step = route_step or request.GET.get(step_param) or (
            "review"
            if _has_submission(assignment, assignment_context)
            else _resume_step(assignment, draft)
            if was_existing
            else "intro"
        )
    else:
        step = route_step or request.POST.get(step_param, "intro")
    try:
        _step(assignment, step)
    except ValueError:
        if request.method == "GET":
            valid_url = _step_url(
                action, query_params, step_param, _resume_step(assignment, draft), step_url_builder
            )
            return redirect(_append_query(valid_url, {"notice": "changed"}))
        return JsonResponse({"error": "Unknown step"}, status=400)
    if request.method == "GET":
        return _render(
            request,
            assignment,
            action=action,
            query_params=query_params,
            step_param=step_param,
            template_name=template_name,
            step=step,
            draft=draft,
            eligibility=eligibility,
            step_url_builder=step_url_builder,
        )
    token = request.POST.get("draft_token", "")
    if token != str(draft.token):
        return _render(
            request,
            assignment,
            action=action,
            query_params=query_params,
            step_param=step_param,
            template_name=template_name,
            step=step,
            draft=draft,
            eligibility=eligibility,
            error="This form is no longer current. Reload before saving again.",
            status=409,
            step_url_builder=step_url_builder,
        )
    intent = request.POST.get("intent", "save")
    if intent not in ("save", "submit"):
        return JsonResponse({"error": "Unknown action"}, status=400)
    try:
        revision = int(request.POST.get("revision", ""))
        if revision < 0:
            raise ValueError
    except ValueError:
        return JsonResponse({"error": "Invalid revision"}, status=400)
    if not eligibility.write or (intent == "submit" and not eligibility.submit):
        return _render(
            request,
            assignment,
            action=action,
            query_params=query_params,
            step_param=step_param,
            template_name=template_name,
            step=step,
            draft=draft,
            eligibility=eligibility,
            error=eligibility.reason or "Homework is closed.",
            status=403,
            step_url_builder=step_url_builder,
        )
    typed_answer = None
    typed_fields = None
    try:
        if step == "review":
            typed_fields = _final_fields_from_post(request, assignment)
            draft = save_final_fields(
                request.user, assignment, values=typed_fields, revision=revision, token=token
            )
        elif step != "intro":
            question = next(q for q in assignment.questions if q.key == step)
            typed_answer = _answer_from_post(request, question)
            draft = save_answer(
                request.user,
                assignment,
                question_key=step,
                answer=typed_answer,
                revision=revision,
                token=token,
            )
        elif revision != draft.revision:
            raise DraftConflict
        if intent == "submit":
            if step != "review":
                return JsonResponse({"error": "Submit from review step"}, status=400)
            result = submit_draft(
                request, assignment, adapter, revision=draft.revision, token=token
            )
            if isinstance(result, HttpResponse):
                return result
            receipt = signing.dumps(
                {"user": request.user.pk, "assignment": assignment.key},
                salt="homework-steps-submitted",
            )
            review_url = _step_url(
                action, query_params, step_param, "review", step_url_builder
            )
            return redirect(_append_query(review_url, {"receipt": receipt}))
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"revision": draft.revision, "saved": True})
        destination = request.POST.get("next_step", step)
        allowed = {step, _step(assignment, step)[0], _step(assignment, step)[2]}
        if destination not in allowed:
            return JsonResponse({"error": "Unknown destination"}, status=400)
        return redirect(
            _step_url(action, query_params, step_param, destination, step_url_builder)
        )
    except DraftConflict:
        draft.refresh_from_db()
        return _render(
            request,
            assignment,
            action=action,
            query_params=query_params,
            step_param=step_param,
            template_name=template_name,
            step=step,
            draft=draft,
            eligibility=eligibility,
            error="This draft changed in another tab. Reload before saving again.",
            status=409,
            typed_answer=typed_answer,
            typed_fields=typed_fields,
            step_url_builder=step_url_builder,
        )
    except ValidationError as exc:
        draft.refresh_from_db()
        return _render(
            request,
            assignment,
            action=action,
            query_params=query_params,
            step_param=step_param,
            template_name=template_name,
            step=step,
            draft=draft,
            eligibility=eligibility,
            error=" ".join(exc.messages),
            status=400,
            typed_answer=typed_answer,
            typed_fields=typed_fields,
            step_url_builder=step_url_builder,
        )
