"""Draft persistence and final handoff; no assessment models are imported here."""

import json
import re

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from community_base.homework_steps.models import HomeworkDraft

KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_TEXT = 10_000
MAX_ANSWER_BYTES = 64_000


class DraftConflict(Exception):
    """The caller's revision is older than the persisted draft."""


def validate_assignment(assignment):
    if not assignment.key or len(assignment.key) > 255:
        raise ValueError("A stable assignment key of at most 255 characters is required")
    if assignment.availability not in ("open", "closed", "scored"):
        raise ValueError("Homework availability must be open, closed, or scored")
    questions = assignment.questions
    if not questions or len(questions) > 100:
        raise ValueError("An assignment needs between 1 and 100 questions")
    keys = [question.key for question in questions]
    if (
        len(set(keys)) != len(keys)
        or any(not KEY_RE.fullmatch(key) for key in keys)
        or {"intro", "review"}.intersection(keys)
    ):
        raise ValueError("Question keys must be unique stable identifiers")
    field_keys = [final_field.key for final_field in assignment.final_fields]
    if len(set(field_keys)) != len(field_keys) or any(
        not KEY_RE.fullmatch(key) for key in field_keys
    ):
        raise ValueError("Final field keys must be unique stable identifiers")
    for question in questions:
        if question.type not in ("choice", "checkbox", "short_text", "long_text"):
            raise ValueError("Unsupported question type")
        if question.type in ("choice", "checkbox"):
            option_keys = [option.key for option in question.options]
            if (
                not option_keys
                or len(option_keys) > 100
                or len(set(option_keys)) != len(option_keys)
            ):
                raise ValueError("Choice questions need unique options")
            if any(not KEY_RE.fullmatch(key) for key in option_keys):
                raise ValueError("Option keys must be stable identifiers")
        elif question.options:
            raise ValueError("Text questions cannot have options")
    if any(field.type not in ("text", "url", "textarea") for field in assignment.final_fields):
        raise ValueError("Unsupported final field type")


def validate_answer(question, answer):
    if question.type in ("short_text", "long_text"):
        if not isinstance(answer, str) or len(answer) > MAX_TEXT:
            raise ValidationError("Enter at most 10,000 characters.")
    elif question.type == "choice":
        if not isinstance(answer, str) or (
            answer and answer not in {o.key for o in question.options}
        ):
            raise ValidationError("Choose one of the available options.")
    else:
        allowed = {o.key for o in question.options}
        if (
            not isinstance(answer, list)
            or len(answer) > len(allowed)
            or any(not isinstance(item, str) or item not in allowed for item in answer)
            or len(set(answer)) != len(answer)
        ):
            raise ValidationError("Choose only the available options.")


def validate_final_field(final_field, value, *, require=False):
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise ValidationError("Enter at most 10,000 characters.")
    if require and final_field.required and not value.strip():
        raise ValidationError(f"{final_field.label} is required.")
    if final_field.type == "url" and value:
        URLValidator(schemes=["http", "https"])(value)


def _bounded(data):
    if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > MAX_ANSWER_BYTES:
        raise ValidationError("The saved answers are too large.")


def get_or_seed_draft(user, assignment):
    """Prefill edits once; subsequent reads never overwrite an in-progress answer."""

    validate_assignment(assignment)
    accepted_answers = (
        assignment.accepted_submission.answers
        if assignment.accepted_submission is not None
        else assignment.existing_answers
    )
    accepted_fields = (
        assignment.accepted_submission.final_fields
        if assignment.accepted_submission is not None
        else assignment.existing_final_fields
    )
    answers = {
        key: value
        for key, value in accepted_answers.items()
        if key in {q.key for q in assignment.questions}
    }
    fields = {
        key: value
        for key, value in accepted_fields.items()
        if key in {f.key for f in assignment.final_fields}
    }
    _bounded({"answers": answers, "final_fields": fields})
    draft, _created = HomeworkDraft.objects.get_or_create(
        user=user,
        assignment_key=assignment.key,
        defaults={"answers": answers, "final_fields": fields},
    )
    return draft


def _save(draft, revision, *, answers=None, final_fields=None):
    updated_answers = draft.answers if answers is None else answers
    updated_fields = draft.final_fields if final_fields is None else final_fields
    _bounded({"answers": updated_answers, "final_fields": updated_fields})
    updated = HomeworkDraft.objects.filter(pk=draft.pk, revision=revision).update(
        answers=updated_answers,
        final_fields=updated_fields,
        revision=revision + 1,
        saved_at=timezone.now(),
    )
    if not updated:
        raise DraftConflict
    return HomeworkDraft.objects.get(pk=draft.pk)


def save_answer(user, assignment, *, question_key, answer, revision, token=None):
    question = next((q for q in assignment.questions if q.key == question_key), None)
    if question is None:
        raise ValidationError("Unknown question.")
    validate_answer(question, answer)
    draft = get_or_seed_draft(user, assignment)
    if token is not None and str(draft.token) != str(token):
        raise DraftConflict
    answers = dict(draft.answers)
    if answer in ("", []):
        answers.pop(question_key, None)
    else:
        answers[question_key] = answer
    return _save(draft, revision, answers=answers)


def save_final_fields(user, assignment, *, values, revision, token=None):
    if set(values) != {field.key for field in assignment.final_fields}:
        raise ValidationError("Unknown final field.")
    for field in assignment.final_fields:
        validate_final_field(field, values[field.key])
    draft = get_or_seed_draft(user, assignment)
    if token is not None and str(draft.token) != str(token):
        raise DraftConflict
    return _save(draft, revision, final_fields=values)


def submit_draft(request, assignment, adapter, *, revision, token):
    """Read the latest authorized draft and let the host do the real submission."""

    with transaction.atomic():
        draft = HomeworkDraft.objects.select_for_update().get(
            user=request.user, assignment_key=assignment.key
        )
        if draft.revision != revision or str(draft.token) != str(token):
            raise DraftConflict
        eligibility = adapter.eligibility(request, assignment)
        if not eligibility.read or not eligibility.submit or assignment.availability != "open":
            raise ValidationError(eligibility.reason or "Homework is closed.")
        questions = {question.key: question for question in assignment.questions}
        if set(draft.answers) - questions.keys():
            raise ValidationError("An answer no longer belongs to this homework.")
        for key, answer in draft.answers.items():
            validate_answer(questions[key], answer)
        fields = {field.key: field for field in assignment.final_fields}
        if set(draft.final_fields) - fields.keys():
            raise ValidationError("A field no longer belongs to this homework.")
        for key, field in fields.items():
            validate_final_field(field, draft.final_fields.get(key, ""), require=True)
        result = adapter.submit(request, assignment, dict(draft.answers), dict(draft.final_fields))
        if result is None:
            raise ValidationError("Submission was not accepted.")
        draft.delete()
        return result


def clear_draft(user, assignment_key):
    """Invalidate an in-progress draft after a host's legacy submission succeeds."""

    HomeworkDraft.objects.filter(user=user, assignment_key=assignment_key).delete()
