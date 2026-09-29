"""Self-paced coursework has no deadlines and reveals homework results on submit (#323)."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils import timezone

from community_base.coursework.models import Homework, HomeworkState, Project, Submission
from community_base.coursework.project_rows import project_row
from community_base.coursework.reminders import homeworks_due_between, projects_collecting_between
from community_base.coursework.scoring import score_homework_submissions
from community_base.coursework.submissions import homework_form_context, submit_homework
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import coursework_cohort, enrollment_for, question

pytestmark = pytest.mark.django_db


def self_paced_cohort():
    return coursework_cohort(slug="self", mode="self_paced")


def test_self_paced_homework_and_project_validate_without_due_dates():
    cohort = self_paced_cohort()
    homework = Homework(cohort=cohort, slug="hw", title="Homework")
    project = Project(cohort=cohort, slug="final", title="Final project")

    homework.full_clean()
    project.full_clean()
    homework.save()
    project.save()

    assert homework.due_date is None
    assert project.submission_due_date is None
    assert project.peer_review_due_date is None


def test_dated_homework_and_project_still_require_due_dates():
    cohort = coursework_cohort(slug="dated")

    with pytest.raises(ValidationError) as homework_error:
        Homework(cohort=cohort, slug="hw", title="Homework").full_clean()
    with pytest.raises(ValidationError) as project_error:
        Project(cohort=cohort, slug="final", title="Final project").full_clean()

    assert set(homework_error.value.message_dict) == {"due_date"}
    assert set(project_error.value.message_dict) == {"submission_due_date", "peer_review_due_date"}


def test_pooled_row_without_dates_shows_no_deadline_before_assignment():
    project = Project.objects.create(cohort=self_paced_cohort(), slug="final", title="Final")

    row = project_row(project, None, completed_reviews=0)
    html = render_to_string("coursework/_project_row.html", {"row": row})

    assert (row.label, row.deadline, row.deadline_kind) == ("Open", None, None)
    assert "data-deadline-kind" not in html
    assert "<time" not in html


def test_dated_row_keeps_its_submission_deadline():
    due = timezone.now() + datetime.timedelta(days=2)
    project = Project.objects.create(
        cohort=coursework_cohort(slug="dated"),
        slug="final",
        title="Final",
        submission_due_date=due,
        peer_review_due_date=due + datetime.timedelta(days=7),
    )

    row = project_row(project, None, completed_reviews=0)

    assert (row.deadline, row.deadline_kind) == (due, "submission")


def test_self_paced_work_gets_no_deadline_reminders_even_with_a_stored_date():
    now = timezone.now()
    soon = now + datetime.timedelta(days=1)
    for cohort in (self_paced_cohort(), coursework_cohort(slug="dated")):
        Homework.objects.create(cohort=cohort, slug="hw", title="Homework", due_date=soon)
        Project.objects.create(
            cohort=cohort,
            slug="final",
            title="Final",
            submission_due_date=soon,
            peer_review_due_date=soon,
        )

    horizon = now + datetime.timedelta(days=3)
    homework_modes = {item.cohort.mode for item in homeworks_due_between(now, horizon)}
    project_modes = {item.cohort.mode for item in projects_collecting_between(now, horizon)}
    assert homework_modes == {"cohort"}
    assert project_modes == {"cohort"}


def answered_homework(cohort):
    homework = Homework.objects.create(cohort=cohort, slug="hw", title="Homework")
    right = question(homework, text="2+2?", correct_answer="4", answer_type="EXS")
    wrong = question(homework, text="3+3?", correct_answer="6", answer_type="EXS")
    return homework, right, wrong


def test_self_paced_homework_is_scored_revealed_and_ranked_on_submit():
    cohort = self_paced_cohort()
    homework, right, wrong = answered_homework(cohort)
    user, _enrollment = enrollment_for(cohort)

    submission = submit_homework(
        homework, user, answers_by_question_id={right.id: "4", wrong.id: "7"}
    )

    context = homework_form_context(homework, user)
    assert context["results_revealed"] is True
    assert context["accepting_submissions"] is False
    assert context["deadline_passed"] is False
    revealed = {
        row_question.id: (result.correct, result.correct_answer)
        for row_question, _answer, result in context["revealed_rows"]
    }
    assert revealed == {right.id: (True, "4"), wrong.id: (False, "6")}
    enrollment = Enrollment.objects.get(cohort=cohort, user=user)
    assert enrollment.total_score == submission.total_score == 1
    assert enrollment.position_on_leaderboard == 1
    homework.refresh_from_db()
    assert homework.state == HomeworkState.OPEN.value


def test_self_paced_homework_rejects_a_second_submission_after_reveal(settings):
    rejected = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_HOMEWORK_SUBMISSION_REJECTED": lambda **event: rejected.append(event),
    }
    cohort = self_paced_cohort()
    homework, right, wrong = answered_homework(cohort)
    user, _enrollment = enrollment_for(cohort)
    submit_homework(homework, user, answers_by_question_id={right.id: "4", wrong.id: "7"})

    second = submit_homework(homework, user, answers_by_question_id={right.id: "4", wrong.id: "6"})

    assert second is None
    assert [event["reason"] for event in rejected] == ["already_submitted"]
    assert Submission.objects.get(homework=homework, student=user).answers.get(
        question=wrong
    ).answer_text == ("7")


def test_rendered_self_paced_form_shows_results_after_submit():
    cohort = self_paced_cohort()
    homework, right, wrong = answered_homework(cohort)
    user, _enrollment = enrollment_for(cohort)
    submit_homework(homework, user, answers_by_question_id={right.id: "4", wrong.id: "7"})

    html = render_to_string("coursework/_homework_form.html", homework_form_context(homework, user))

    assert 'data-correct="true"' in html
    assert 'data-correct="false"' in html
    assert "Correct answer: 6" in html
    assert "<form" not in html


def test_dated_homework_reveals_nothing_until_scored():
    cohort = coursework_cohort(slug="dated")
    homework, right, wrong = answered_homework(cohort)
    Homework.objects.filter(pk=homework.pk).update(
        due_date=timezone.now() + datetime.timedelta(days=3)
    )
    homework.refresh_from_db()
    user, _enrollment = enrollment_for(cohort)
    submit_homework(homework, user, answers_by_question_id={right.id: "4", wrong.id: "7"})

    before = homework_form_context(homework, user)
    html = render_to_string("coursework/_homework_form.html", before)
    assert before["results_revealed"] is False
    assert before["revealed_rows"] == []
    assert before["accepting_submissions"] is True
    assert "Correct answer" not in html
    assert "data-correct" not in html

    Homework.objects.filter(pk=homework.pk).update(
        due_date=timezone.now() - datetime.timedelta(days=1)
    )
    status, _message = score_homework_submissions(homework.pk)
    assert status.value == "OK"
    homework.refresh_from_db()

    after = homework_form_context(homework, user)
    assert after["results_revealed"] is True
    assert len(after["revealed_rows"]) == 2
