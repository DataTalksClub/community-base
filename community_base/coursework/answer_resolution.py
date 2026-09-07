"""Resolve legacy and source-managed homework answers at one boundary.

DB-managed questions use ``correct_answer`` exactly as stored. Source-managed
questions carry an encrypted answer envelope: the package decrypts only at
this boundary and converts stable source option IDs back to the one-based
indices expected by the answer-checking code.

The keyring is loaded from ``COMMUNITY_BASE["COURSEWORK_ANSWER_KEYRING"]``.
Without a configured keyring, an envelope question raises
``HomeworkAnswerKeyUnavailable`` instead of silently failing an answer.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from community_base.coursework.answer_crypto import (
    AnswerPayload,
    HomeworkAnswerCryptoError,
    HomeworkAnswerKeyring,
    HomeworkAnswerKeyUnavailable,
    decrypt_answer,
    parse_keyring,
)
from community_base.kernel.conf import get

if TYPE_CHECKING:
    from community_base.coursework.models import Question

CONFIG_KEY = "COURSEWORK_ANSWER_KEYRING"


def configured_keyring() -> HomeworkAnswerKeyring:
    """Load the dedicated answer keyring from the package configuration."""

    serialized = get(CONFIG_KEY)
    if not serialized:
        raise HomeworkAnswerKeyUnavailable("homework answer key is unavailable")
    return parse_keyring(serialized)


def resolve_correct_answer(
    question: Question,
    *,
    keyring: HomeworkAnswerKeyring | None = None,
) -> str:
    """Return the canonical answer representation for a question."""

    if question.answer_envelope is None:
        return question.correct_answer or ""

    if not question.source_question_id:
        raise HomeworkAnswerCryptoError("source question identity is missing")

    answer_keyring = keyring or configured_keyring()
    payload = decrypt_answer(
        question.answer_envelope,
        course_slug=question.homework.cohort.course.slug,
        homework_slug=question.homework.slug,
        question_id=question.source_question_id,
        keyring=answer_keyring,
    )
    if question.has_choice_answers():
        return _choice_answer_indices(question, payload)
    return _free_form_answer(payload)


def _choice_answer_indices(question: Question, payload: AnswerPayload) -> str:
    option_ids = payload.get("option_ids")
    source_option_ids = question.source_option_ids
    if (
        not isinstance(option_ids, list)
        or not option_ids
        or not isinstance(source_option_ids, list)
    ):
        raise HomeworkAnswerCryptoError("source choice answer is invalid")

    positions = {option_id: index for index, option_id in enumerate(source_option_ids, start=1)}
    try:
        indices = [positions[option_id] for option_id in option_ids]
    except (KeyError, TypeError):
        raise HomeworkAnswerCryptoError("source choice answer is invalid") from None
    if len(set(indices)) != len(indices):
        raise HomeworkAnswerCryptoError("source choice answer is invalid")
    return ",".join(str(index) for index in indices)


def _free_form_answer(payload: AnswerPayload) -> str:
    if set(payload) != {"value"}:
        raise HomeworkAnswerCryptoError("source free-form answer is invalid")
    value = payload["value"]
    if value is None:
        return ""
    if isinstance(value, bool):
        return json.dumps(value)
    return str(value)
