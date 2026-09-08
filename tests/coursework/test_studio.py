"""Studio surfaces for coursework: cohort admin, homework actions, submission edits.

Donor mapping: ``studio_courses/tests/test_homework_views.py``,
``test_homework_submission_edit_views.py``, ``test_course_views.py`` and the
route-ownership core of ``test_studio_course_routes.py``. Donor datamailer,
impersonation, cloudwatch and design-system tests stay site-side.
"""

import datetime

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import (
    Answer,
    HomeworkState,
    Question,
    QuestionTypes,
    Submission,
)
from community_base.coursework.scoring import score_homework_submissions
from community_base.coursework.studio_services import fill_correct_answers
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import (
    coursework_cohort,
    enrollment_for,
)
from tests.coursework.test_models import (
    homework as make_homework,
)
from tests.coursework.test_models import (
    question as make_question,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = User.objects.create_user(email="staff@example.com", is_staff=True)
    client.force_login(user)
    return user


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def due_yesterday(cohort):
    return make_homework(cohort, due_date=timezone.now() - datetime.timedelta(hours=1))


def choice_question(homework, **values):
    values.setdefault("text", "Pick one")
    values.setdefault("question_type", QuestionTypes.MULTIPLE_CHOICE.value)
    values.setdefault("possible_answers", "A\nB\nC")
    values.setdefault("correct_answer", "2")
    return Question.objects.create(homework=homework, **values)


def submission_with_answer(homework, enrollment, question, answer_text, **submission_values):
    submission = Submission.objects.create(
        homework=homework,
        student=enrollment.user,
        enrollment=enrollment,
        **submission_values,
    )
    Answer.objects.create(submission=submission, question=question, answer_text=answer_text)
    return submission


def test_cohort_list_requires_staff(client):
    cohort = coursework_cohort()

    anonymous = client.get(reverse("coursework_studio_cohort_list"))
    client.force_login(User.objects.create_user(email="learner@example.com"))
    forbidden = client.get(reverse("coursework_studio_cohort_list"))

    assert anonymous.status_code == 302
    assert forbidden.status_code == 403
    assert cohort.title


def test_cohort_list_and_admin_render(client, staff):
    cohort = coursework_cohort()
    homework = due_yesterday(cohort)
    question = choice_question(homework)
    _user, enrollment = enrollment_for(cohort)
    submission_with_answer(homework, enrollment, question, "2")

    listed = client.get(reverse("coursework_studio_cohort_list"))
    admin = client.get(reverse("coursework_studio_cohort", args=[cohort.pk]))

    assert listed.status_code == 200
    assert cohort.title in listed.content.decode()
    assert admin.status_code == 200
    assert homework.title in admin.content.decode()
    assert admin.context["support_metrics"]["total_enrollments"] == 1


def test_cohort_admin_shows_action_flags_per_state(client, staff):
    cohort = coursework_cohort()
    open_homework = make_homework(cohort, slug="hw-open")
    scored_homework = make_homework(cohort, slug="hw-scored", state=HomeworkState.SCORED.value)

    response = client.get(reverse("coursework_studio_cohort", args=[cohort.pk]))

    rows = {row.homework.slug: row for row in response.context["homeworks"]}
    assert rows[open_homework.slug].can_score is True
    assert rows[open_homework.slug].can_extend_deadline is True
    assert rows[scored_homework.slug].can_score is False
    assert rows[scored_homework.slug].can_extend_deadline is False


def test_homework_score_scores_submissions_and_redirects(client, staff):
    cohort = coursework_cohort()
    homework = due_yesterday(cohort)
    question = choice_question(homework)
    _user, enrollment = enrollment_for(cohort)
    submission = submission_with_answer(homework, enrollment, question, "2")

    response = client.post(reverse("coursework_studio_homework_score", args=[homework.pk]))

    homework.refresh_from_db()
    submission.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("coursework_studio_cohort", args=[cohort.pk])
    assert homework.state == HomeworkState.SCORED.value
    assert submission.total_score == 1
    assert any("scored" in message for message in messages_of(response))


def test_homework_score_warns_when_due_date_is_in_the_future(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)

    response = client.post(
        reverse("coursework_studio_homework_score", args=[homework.pk]), follow=True
    )

    assert any("due date" in message for message in messages_of(response))
    homework.refresh_from_db()
    assert homework.state == HomeworkState.OPEN.value


def test_homework_rescore_reruns_scoring(client, staff):
    cohort = coursework_cohort()
    homework = due_yesterday(cohort)
    question = choice_question(homework)
    _user, enrollment = enrollment_for(cohort)
    submission = submission_with_answer(homework, enrollment, question, "2")
    status, _message = score_homework_submissions(homework.id)
    assert status.value == "OK"
    # The operator fixes a wrong answer key after the first scoring pass.
    question.correct_answer = "1"
    question.save()

    response = client.post(reverse("coursework_studio_homework_rescore", args=[homework.pk]))

    homework.refresh_from_db()
    submission.refresh_from_db()
    assert response.status_code == 302
    assert homework.state == HomeworkState.SCORED.value
    assert submission.questions_score == 0
    assert submission.total_score == 0
    assert submission.answers.get().is_correct is False


def test_homework_rescore_warns_for_unscored_homework(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)

    response = client.post(
        reverse("coursework_studio_homework_rescore", args=[homework.pk]), follow=True
    )

    assert any("not scored" in message for message in messages_of(response))
    homework.refresh_from_db()
    assert homework.state == HomeworkState.OPEN.value


def test_homework_extend_deadline_moves_due_date(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    before = homework.due_date

    response = client.post(
        reverse("coursework_studio_homework_extend_deadline", args=[homework.pk]), {"days": "3"}
    )

    homework.refresh_from_db()
    assert response.status_code == 302
    assert homework.due_date - before == datetime.timedelta(days=3)
    assert any("Extended" in message for message in messages_of(response))


def test_homework_extend_deadline_rejects_invalid_days(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    before = homework.due_date

    for raw in ("2", "thirty", ""):
        response = client.post(
            reverse("coursework_studio_homework_extend_deadline", args=[homework.pk]),
            {"days": raw},
        )

        assert any("Invalid deadline extension" in message for message in messages_of(response))
    homework.refresh_from_db()
    assert homework.due_date == before


def test_homework_extend_deadline_not_allowed_when_scored(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort, state=HomeworkState.SCORED.value)
    before = homework.due_date

    response = client.post(
        reverse("coursework_studio_homework_extend_deadline", args=[homework.pk]), {"days": "1"}
    )

    homework.refresh_from_db()
    assert any("Only open homework" in message for message in messages_of(response))
    assert homework.due_date == before


def test_homework_actions_honour_safe_next_and_ignore_unsafe(client, staff):
    cohort = coursework_cohort()
    homework = due_yesterday(cohort)
    question = choice_question(homework)
    _user, enrollment = enrollment_for(cohort)
    submission_with_answer(homework, enrollment, question, "2")
    submissions_url = reverse("coursework_studio_homework_submissions", args=[homework.pk])

    safe = client.post(
        reverse("coursework_studio_homework_score", args=[homework.pk]),
        {"next": submissions_url},
    )
    unsafe = client.post(
        reverse("coursework_studio_homework_extend_deadline", args=[homework.pk]),
        {"days": "1", "next": "https://evil.example/phish"},
    )

    assert safe.status_code == 302
    assert safe.url == submissions_url
    assert unsafe.status_code == 302
    assert unsafe.url == reverse("coursework_studio_cohort", args=[cohort.pk])


def test_homework_set_correct_answers_uses_most_frequent_answer(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    question = choice_question(homework, correct_answer="")
    _user, enrollment = enrollment_for(cohort)
    submission = Submission.objects.create(
        homework=homework, student=enrollment.user, enrollment=enrollment
    )
    for answer_text in ("3", "3", "1"):
        Answer.objects.create(submission=submission, question=question, answer_text=answer_text)

    response = client.post(
        reverse("coursework_studio_homework_set_correct_answers", args=[homework.pk])
    )

    question.refresh_from_db()
    assert response.status_code == 302
    assert question.correct_answer == "3"
    assert any("most popular" in message for message in messages_of(response))


def test_fill_correct_answers_skips_questions_with_valid_keys():
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    valid = choice_question(homework, correct_answer="2")
    broken = choice_question(
        homework, text="Broken key", possible_answers="A\nB", correct_answer="9"
    )
    _user, enrollment = enrollment_for(cohort)
    submission = Submission.objects.create(
        homework=homework, student=enrollment.user, enrollment=enrollment
    )
    for answer_text in ("2", "1"):
        Answer.objects.create(submission=submission, question=broken, answer_text=answer_text)

    updated = fill_correct_answers(homework)

    valid.refresh_from_db()
    broken.refresh_from_db()
    assert updated == 1
    assert valid.correct_answer == "2"
    assert broken.correct_answer == "2"


def test_homework_clear_correct_answers_removes_all(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    first = choice_question(homework)
    second = make_question(homework, text="Explain", correct_answer="expected answer")

    response = client.post(
        reverse("coursework_studio_homework_clear_correct_answers", args=[homework.pk]),
        follow=True,
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.correct_answer == ""
    assert second.correct_answer == ""
    assert any("2 questions" in message for message in messages_of(response))


def test_homework_save_answers_updates_questions(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    first = make_question(homework, text="What is 2+2?")
    second = make_question(homework, text="Introduce yourself")

    response = client.post(
        reverse("coursework_studio_homework_save_answers", args=[homework.pk]),
        {
            f"correct_answer_{first.id}": "4",
            f"answer_type_{first.id}": "INT",
            f"correct_answer_{second.id}": "3",
            f"answer_type_{second.id}": "",
        },
        follow=True,
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert response.status_code == 200
    assert first.correct_answer == "4"
    assert first.answer_type == "INT"
    assert second.correct_answer == "3"
    assert second.answer_type is None
    assert any("updated" in message for message in messages_of(response))


def test_homework_save_choice_answers_with_multiple_selections(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    checkboxes = Question.objects.create(
        homework=homework,
        text="Select all that apply",
        question_type=QuestionTypes.CHECKBOXES.value,
        possible_answers="Alpha\nBeta\nGamma",
        scores_for_correct_answer=1,
    )

    response = client.post(
        reverse("coursework_studio_homework_save_answers", args=[homework.pk]),
        {f"correct_answer_{checkboxes.id}": ["1", "3"]},
    )

    checkboxes.refresh_from_db()
    assert response.status_code == 302
    assert checkboxes.correct_answer == "1,3"


def test_submissions_page_renders_choice_checkboxes_pre_checked(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    choice_question(homework, possible_answers="London\nParis\nBerlin")

    response = client.get(reverse("coursework_studio_homework_submissions", args=[homework.pk]))

    body = response.content.decode()
    assert response.status_code == 200
    assert 'type="checkbox"' in body
    assert "London" in body and "Paris" in body and "Berlin" in body
    assert "checked" in body


def test_homework_submissions_search_finds_email_and_display_name(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    question = choice_question(homework)
    _target_user, target_enrollment = enrollment_for(cohort, email="findme@example.com")
    Enrollment.objects.filter(id=target_enrollment.id).update(display_name="Findable Learner")
    other_user, _other_enrollment = enrollment_for(cohort, email="other@example.com")
    submission_with_answer(homework, target_enrollment, question, "2")
    submission_with_answer(
        homework,
        Enrollment.objects.get(user=other_user, cohort=cohort),
        question,
        "2",
    )

    by_email = client.get(
        reverse("coursework_studio_homework_submissions", args=[homework.pk]), {"q": "findme"}
    )
    by_display_name = client.get(
        reverse("coursework_studio_homework_submissions", args=[homework.pk]),
        {"q": "Findable"},
    )

    assert by_email.context["submissions"].paginator.count == 1
    assert by_display_name.context["submissions"].paginator.count == 1


def test_homework_submission_edit_get_renders_answer_fields(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    question = choice_question(homework)
    _user, enrollment = enrollment_for(cohort)
    submission = submission_with_answer(homework, enrollment, question, "2")

    response = client.get(
        reverse("coursework_studio_homework_submission_edit", args=[homework.pk, submission.pk])
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert f'name="answer_{question.id}"' in body
    assert 'name="learning_in_public_links"' in body
    assert 'name="faq_contribution_url"' in body
    assert 'name="faq_score"' in body


def test_homework_submission_edit_post_updates_answers_and_scores(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    first = choice_question(homework)
    second = choice_question(homework, text="Pick another", possible_answers="X\nY\nZ")
    _user, enrollment = enrollment_for(cohort)
    submission = submission_with_answer(homework, enrollment, first, "2")
    Answer.objects.create(submission=submission, question=second, answer_text="1")

    response = client.post(
        reverse("coursework_studio_homework_submission_edit", args=[homework.pk, submission.pk]),
        {
            f"answer_{first.id}": "2",
            f"answer_{second.id}": "2",
            "learning_in_public_links": "https://example.com/post1\nhttps://example.com/post2",
            "faq_contribution_url": "",
        },
    )

    submission.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("coursework_studio_homework_submissions", args=[homework.pk])
    assert submission.answers.get(question=second).answer_text == "2"
    assert submission.learning_in_public_links == [
        "https://example.com/post1",
        "https://example.com/post2",
    ]
    assert submission.questions_score == 2
    assert submission.learning_in_public_score == 2
    assert submission.total_score == 4


def test_homework_submission_edit_updates_faq_entry_and_score(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    question = choice_question(homework)
    _user, enrollment = enrollment_for(cohort)
    submission = submission_with_answer(homework, enrollment, question, "1")

    faq_entry = "https://gist.github.com/example/not-validated-here"
    response = client.post(
        reverse("coursework_studio_homework_submission_edit", args=[homework.pk, submission.pk]),
        {
            f"answer_{question.id}": "2",
            "learning_in_public_links": "",
            "faq_contribution_url": faq_entry,
            "faq_score": "3",
        },
    )

    submission.refresh_from_db()
    assert response.status_code == 302
    assert submission.faq_contribution_url == faq_entry
    assert submission.faq_score == 3
    assert submission.questions_score == 1
    assert submission.total_score == 4


def test_homework_submission_edit_triggers_leaderboard_update(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    question = choice_question(homework)
    _user, enrollment = enrollment_for(cohort)
    submission = submission_with_answer(homework, enrollment, question, "1")
    Enrollment.objects.filter(id=enrollment.id).update(total_score=0, position_on_leaderboard=999)

    response = client.post(
        reverse("coursework_studio_homework_submission_edit", args=[homework.pk, submission.pk]),
        {f"answer_{question.id}": "2", "learning_in_public_links": ""},
    )

    enrollment.refresh_from_db()
    assert response.status_code == 302
    assert enrollment.total_score == 1
    assert enrollment.position_on_leaderboard == 1


def test_homework_submission_edit_invalid_post_rerenders_with_error(client, staff):
    cohort = coursework_cohort()
    homework = make_homework(cohort)
    question = choice_question(homework)
    _user, enrollment = enrollment_for(cohort)
    submission = submission_with_answer(homework, enrollment, question, "2")

    response = client.post(
        reverse("coursework_studio_homework_submission_edit", args=[homework.pk, submission.pk]),
        {
            f"answer_{question.id}": "2",
            "faq_score": "not-a-number",
        },
        follow=True,
    )

    submission.refresh_from_db()
    assert response.status_code == 200
    assert any("Error updating submission" in message for message in messages_of(response))
    # The unscored submission keeps its stored scores; nothing was saved.
    assert submission.total_score == 0


def test_studio_section_registered_with_coursework_routes():
    from community_base.studio.registry import sections

    section = next(item for item in sections() if item.slug == "coursework")
    destination = section.destinations[0]

    assert section.title == "Coursework"
    assert destination.url_name == "coursework_studio_cohort_list"
    for route in (
        "coursework_studio_homework_score",
        "coursework_studio_homework_rescore",
        "coursework_studio_homework_submissions",
        "coursework_studio_homework_submission_edit",
    ):
        assert route in destination.route_names
