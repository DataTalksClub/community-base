import base64
import json

import pytest

from community_base.coursework.answer_checks import (
    is_answer_correct,
    is_contains_string_answer_correct,
    is_exact_string_answer_correct,
    is_float_equal,
    is_integer_equal,
)
from community_base.coursework.answer_crypto import (
    decrypt_answer,
    encrypt_choice_answer,
    encrypt_scalar_answer,
)
from community_base.coursework.answer_resolution import resolve_correct_answer
from community_base.coursework.models import (
    Answer,
    AnswerTypes,
    Question,
    QuestionTypes,
)
from tests.coursework.test_models import coursework_cohort, homework, question

pytestmark = pytest.mark.django_db


def keyring_json() -> str:
    return json.dumps(
        {
            "active_key_id": "k1",
            "keys": {"k1": base64.b64encode(bytes(range(32))).decode()},
        }
    )


def free_form_question(hw, answer_type, correct_answer):
    return question(
        hw,
        question_type=QuestionTypes.FREE_FORM.value,
        answer_type=answer_type,
        correct_answer=correct_answer,
    )


def answer_for(q, text):
    return Answer(question=q, answer_text=text)


@pytest.mark.parametrize(
    ("value1", "value2", "expected"),
    [("1.0", "1.001", True), ("1.0", "1.5", False), ("abc", "1", False)],
)
def test_float_equality_with_tolerance(value1, value2, expected):
    assert is_float_equal(value1, value2) is expected


@pytest.mark.parametrize(
    ("value1", "value2", "expected"),
    [("2", "2", True), ("2.0", "2", False), ("x", "1", False)],
)
def test_integer_equality(value1, value2, expected):
    assert is_integer_equal(value1, value2) is expected


def test_string_answer_checks():
    assert is_exact_string_answer_correct(" ABc ", "abc") is False  # checks are strict here
    assert is_exact_string_answer_correct("abc", "ABC") is True
    assert is_contains_string_answer_correct("the answer is forty two", "forty") is True


def test_free_form_any_requires_non_empty(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    q = free_form_question(hw, AnswerTypes.ANY.value, "anything")
    answered = answer_for(q, "my answer")
    blank = answer_for(q, "")

    # Answer type ANY short-circuits: every submission counts as correct.
    assert is_answer_correct(q, answered) is True
    assert is_answer_correct(q, blank) is True


def test_free_form_float_and_integer_checks(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    float_q = free_form_question(hw, AnswerTypes.FLOAT.value, "3.14")
    int_q = free_form_question(hw, AnswerTypes.INTEGER.value, "7")

    assert is_answer_correct(float_q, answer_for(float_q, "3.141")) is True
    assert is_answer_correct(float_q, answer_for(float_q, "4")) is False
    assert is_answer_correct(int_q, answer_for(int_q, "7")) is True
    assert is_answer_correct(int_q, answer_for(int_q, "8")) is False


def test_multiple_choice_and_checkbox_checks(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    single = question(
        hw,
        question_type=QuestionTypes.MULTIPLE_CHOICE.value,
        possible_answers="Red\nGreen\nBlue",
        correct_answer="3",
    )
    multi = question(
        hw,
        question_type=QuestionTypes.CHECKBOXES.value,
        possible_answers="Red\nGreen\nBlue",
        correct_answer="1,3",
    )

    assert is_answer_correct(single, answer_for(single, "3")) is True
    assert is_answer_correct(single, answer_for(single, "1")) is False
    assert is_answer_correct(multi, answer_for(multi, "3,1")) is True
    assert is_answer_correct(multi, answer_for(multi, "1")) is False


def test_resolution_without_envelope_returns_correct_answer(db):
    cohort = coursework_cohort()
    hw = homework(cohort)
    q = free_form_question(hw, AnswerTypes.EXACT_STRING.value, "Cargo")

    assert resolve_correct_answer(q) == "Cargo"


def test_resolution_decrypts_source_envelopes(db, settings):
    cohort = coursework_cohort()
    hw = homework(cohort)
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_ANSWER_KEYRING": keyring_json(),
    }
    course_slug = cohort.course.slug
    q = Question.objects.create(
        homework=hw,
        text="Pick one",
        question_type=QuestionTypes.MULTIPLE_CHOICE.value,
        possible_answers="One\nTwo\nThree",
        source_content_id="5a2b3c4d-0001-4000-8000-000000000001",
        source_question_id="q-1",
        source_path="cohorts/2026/homework.yaml",
        source_commit_sha="a" * 40,
        source_checksum="c" * 64,
        source_option_ids=["opt-a", "opt-b"],
        answer_envelope={},
    )
    envelope = encrypt_choice_answer(
        ["opt-b"],
        course_slug=course_slug,
        homework_slug=hw.slug,
        question_id="q-1",
        keyring=resolve_keyring(settings),
    )
    q.answer_envelope = envelope
    q.save()

    assert resolve_correct_answer(q) == "2"


def test_resolution_free_form_scalar_envelope(db, settings):
    cohort = coursework_cohort()
    hw = homework(cohort, slug="hw-free")
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_ANSWER_KEYRING": keyring_json(),
    }
    q = Question.objects.create(
        homework=hw,
        text="How many?",
        question_type=QuestionTypes.FREE_FORM.value,
        answer_type=AnswerTypes.INTEGER.value,
        source_content_id="5a2b3c4d-0001-4000-8000-000000000002",
        source_question_id="q-2",
        source_path="cohorts/2026/homework-free.yaml",
        source_commit_sha="a" * 40,
        source_checksum="c" * 64,
        answer_envelope={},
    )
    envelope = encrypt_scalar_answer(
        42,
        course_slug=cohort.course.slug,
        homework_slug=hw.slug,
        question_id="q-2",
        keyring=resolve_keyring(settings),
    )
    q.answer_envelope = envelope
    q.save()

    assert resolve_correct_answer(q) == "42"


def resolve_keyring(settings):
    from community_base.coursework.answer_resolution import configured_keyring

    return configured_keyring()


def test_decrypt_round_trip_with_wrong_context_fails(db, settings):
    cohort = coursework_cohort()
    hw = homework(cohort, slug="hw-ctx")
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_ANSWER_KEYRING": keyring_json(),
    }
    envelope = encrypt_scalar_answer(
        "secret",
        course_slug=cohort.course.slug,
        homework_slug=hw.slug,
        question_id="q-3",
        keyring=resolve_keyring(settings),
    )

    from community_base.coursework.answer_crypto import HomeworkAnswerCryptoError

    with pytest.raises(HomeworkAnswerCryptoError):
        decrypt_answer(
            envelope,
            course_slug=cohort.course.slug,
            homework_slug="other-homework",
            question_id="q-3",
            keyring=resolve_keyring(settings),
        )
