"""Host-supplied per-question results on the Review step and each question step (#323)."""

import datetime
from dataclasses import replace

import pytest
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import Homework
from community_base.homework_steps.coursework import CourseworkAdapter, coursework_assignment
from community_base.homework_steps.services import save_answer, submit_draft
from community_base.homework_steps.types import (
    AcceptedSubmission,
    Assignment,
    Option,
    Question,
    QuestionResult,
)
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_models import question as make_question
from tests.homework_steps.test_coursework import _request
from tests.homework_steps.test_flow import Adapter, flow

pytestmark = pytest.mark.django_db

RESULTS = {
    "q1": QuestionResult(correct=False, correct_answer="Beta", explanation="Beta is the one."),
    "q2": QuestionResult(correct=True, correct_answer="Because."),
}


@pytest.fixture
def user():
    return User.objects.create_user(email="reveal@example.com")


def scored_assignment(**values):
    values.setdefault("availability", "scored")
    values.setdefault("question_results", RESULTS)
    return Assignment(
        key="course:cohort-1:homework-1",
        title="Homework one",
        questions=(
            Question("q1", "Choose one", "choice", (Option("a", "Alpha"), Option("b", "Beta"))),
            Question("q2", "Explain", "long_text"),
        ),
        accepted_submission=AcceptedSubmission(answers={"q1": "a", "q2": "Because."}),
        **values,
    )


def page(user, assignment, step):
    return flow(user, assignment, Adapter(), query=f"?homework_step={step}").content.decode()


def test_review_step_shows_each_revealed_result_beside_the_accepted_answer(user):
    html = page(user, scored_assignment(), "review")

    assert html.count('class="homework-question-result"') == 2
    assert 'data-correct="false"' in html
    assert "Correct answer: Beta" in html
    assert "Beta is the one." in html


def test_question_step_shows_its_own_result(user):
    html = page(user, scored_assignment(), "q2")

    assert html.count('class="homework-question-result"') == 1
    assert 'data-correct="true"' in html
    assert "Correct answer: Because." in html


def test_no_results_render_when_the_host_reveals_none(user):
    html = page(user, scored_assignment(question_results=None), "review")

    assert "homework-question-result" not in html
    assert "Correct answer" not in html


def test_results_never_render_beside_an_open_draft(user):
    html = page(user, scored_assignment(availability="open"), "review")

    assert "homework-question-result" not in html


def coursework_homework(cohort):
    homework = Homework.objects.create(
        cohort=cohort,
        slug="hw",
        title="Homework",
        due_date=timezone.now() + datetime.timedelta(days=3),
    )
    question = make_question(homework, text="2+2?", correct_answer="4", answer_type="EXS")
    return homework, f"db-{question.pk}"


def submit_through_stepper(homework, user, key, answer):
    assignment = coursework_assignment(homework, user)
    draft = save_answer(user, assignment, question_key=key, answer=answer, revision=0)
    submit_draft(
        _request(user),
        assignment,
        CourseworkAdapter(homework),
        revision=draft.revision,
        token=draft.token,
    )


def test_self_paced_coursework_homework_is_scored_and_revealed_after_submit(user):
    homework, key = coursework_homework(coursework_cohort(slug="self", mode="self_paced"))

    before = coursework_assignment(homework, user)
    assert (before.availability, before.question_results) == ("open", None)

    submit_through_stepper(homework, user, key, "5")

    after = coursework_assignment(homework, user)
    assert after.availability == "scored"
    assert after.question_results == {key: QuestionResult(correct=False, correct_answer="4")}
    eligibility = CourseworkAdapter(homework).eligibility(_request(user), after)
    assert (eligibility.write, eligibility.submit) == (False, False)
    html = page(user, replace(after, context=None), "review")
    assert "Correct answer: 4" in html
    assert "Submit homework" not in html


def test_dated_coursework_homework_reveals_nothing_before_scoring(user):
    homework, key = coursework_homework(coursework_cohort(slug="dated"))

    submit_through_stepper(homework, user, key, "5")

    after = coursework_assignment(homework, user)
    assert (after.availability, after.question_results) == ("open", None)
    html = page(user, after, "review")
    assert "homework-question-result" not in html
    assert "Correct answer" not in html
