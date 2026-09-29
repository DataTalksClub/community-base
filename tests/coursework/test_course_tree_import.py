"""Course-tree assignment import, identity, ordering and scoring behavior."""

import shutil

import pytest

from community_base.accounts.models import User
from community_base.content_sync.models import SyncStatus
from community_base.coursework.models import Answer, Homework, Question, Submission
from community_base.coursework.question_order import ordered_questions
from community_base.coursework.submissions import submit_homework
from community_base.curriculum.models import Enrollment, Unit, UnitProgress
from tests.coursework.test_course_tree import (
    COHORT,
    FIRST_ID,
    SECOND_ID,
    SOURCE,
    UNIT_ID,
    fixture,
    sync,
)
from tests.coursework.test_course_tree import (
    course_parser as course_parser,
)


@pytest.fixture(autouse=True)
def registered_parser(course_parser):
    yield


@pytest.mark.django_db
def test_one_source_binds_two_cohorts_and_removing_one_binding_cleans_only_its_assignment(tmp_path):
    root = fixture(tmp_path)
    second = root / "cohorts/2027"
    second.mkdir()
    cohort = (root / COHORT).read_text()
    cohort = cohort.replace("000000000001", "000000000003", 1)
    cohort = cohort.replace("2026", "2027")
    cohort = cohort.replace("    source: homework/core/homework.yaml\n", "")
    cohort = cohort.replace("    unit: 9a2b3c4d-0003-4000-8000-000000000002\n", "")
    cohort = cohort.replace(
        "homework:\n  - module: core\n  - module: core", "homework:\n  - module: core"
    )
    (second / "cohort.yaml").write_text(cohort)
    assert sync(root).status == SyncStatus.SUCCESS
    assignments = list(Homework.objects.filter(source_content_id=UNIT_ID).order_by("cohort__slug"))
    assert [item.cohort.slug for item in assignments] == ["2026", "2027"]
    assert assignments[0].pk != assignments[1].pk

    (second / "cohort.yaml").write_text(cohort.split("homework:\n")[0])
    assert sync(root).status == SyncStatus.SUCCESS
    assert list(
        Homework.objects.filter(source_content_id=UNIT_ID).values_list("pk", flat=True)
    ) == [assignments[0].pk]


@pytest.mark.django_db
def test_source_edits_flow_through_and_binding_overrides_remain_cohort_specific(tmp_path):
    root = fixture(tmp_path)
    _set_cohort_override(root, enabled=True)
    assert sync(root).status == SyncStatus.SUCCESS
    homework = Homework.objects.get(source_content_id=UNIT_ID)
    assert homework.due_date.day == 9
    assert homework.learning_in_public_cap == 7
    path = root / SOURCE
    path.write_text(
        path.read_text()
        .replace("2026-10-01", "2026-10-03")
        .replace("learning_in_public_cap: 4", "learning_in_public_cap: 5")
    )
    assert sync(root).status == SyncStatus.SUCCESS
    homework.refresh_from_db()
    assert homework.due_date.day == 9
    assert homework.learning_in_public_cap == 7
    _set_cohort_override(root, enabled=False)
    assert sync(root).status == SyncStatus.SUCCESS
    homework.refresh_from_db()
    assert homework.due_date.day == 3
    assert homework.learning_in_public_cap == 5


def _set_cohort_override(root, *, enabled):
    path = root / COHORT
    binding = f"    unit: {UNIT_ID}\n"
    override = "    due_at: 2026-10-09T23:00:00+00:00\n    form:\n      learning_in_public_cap: 7\n"
    if enabled:
        path.write_text(path.read_text().replace(binding, binding + override))
    else:
        path.write_text(path.read_text().replace(override, ""))


def _move_authored_source(root):
    old = root / SOURCE
    prefix, first_block, second_block = old.read_text().split("  - content_id: ")
    old.write_text(prefix + "  - content_id: " + second_block + "  - content_id: " + first_block)
    target = root / "02-advanced/03-quiz"
    shutil.move(str(old.parent), str(target))
    cohort_path = root / COHORT
    cohort_path.write_text(
        cohort_path.read_text()
        .replace("modules:\n  - core", "modules:\n  - core\n  - advanced")
        .replace(
            f"  - module: core\n    unit: {UNIT_ID}", f"  - module: advanced\n    unit: {UNIT_ID}"
        )
    )


@pytest.mark.django_db
def test_source_move_and_question_reorder_preserve_learner_records(tmp_path):
    root = fixture(tmp_path)
    assert sync(root).status == SyncStatus.SUCCESS
    homework = Homework.objects.get(source_content_id=UNIT_ID)
    unit = Unit.objects.get(source_content_id=UNIT_ID)
    first, second = homework.questions.order_by("authored_position")
    user = User.objects.create_user(email="fixture@example.invalid")
    enrollment = Enrollment.objects.create(user=user, cohort=homework.cohort)
    submission = Submission.objects.create(homework=homework, student=user, enrollment=enrollment)
    answer = Answer.objects.create(submission=submission, question=first, answer_text="2")
    progress = UnitProgress.objects.create(user=user, unit=unit)
    ids = (homework.pk, unit.pk, first.pk, second.pk, submission.pk, answer.pk, progress.pk)

    _move_authored_source(root)

    assert sync(root).status == SyncStatus.SUCCESS
    homework.refresh_from_db()
    unit.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert (homework.pk, unit.pk, first.pk, second.pk, submission.pk, answer.pk, progress.pk) == ids
    assert homework.module.slug == "advanced"
    assert unit.module.slug == "advanced"
    assert [item.pk for item in homework.questions.order_by("authored_position")] == [
        second.pk,
        first.pk,
    ]
    assert Answer.objects.get(pk=answer.pk).answer_text == "2"


@pytest.mark.django_db
def test_plaintext_correct_is_hidden_on_ordinary_unit_page(settings, client, tmp_path):
    settings.ROOT_URLCONF = "tests.coursework.test_course_tree"
    root = fixture(tmp_path)
    assert sync(root).status == SyncStatus.SUCCESS
    client.force_login(User.objects.create_user(email="viewer@example.invalid"))

    response = client.get("/courses/ml-zoomcamp/2026/core/quiz/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Read the quiz instructions." in body
    assert "Give the exact name" in body
    assert "Cargo" not in body


@pytest.mark.django_db
def test_scoring_and_reveal_use_the_existing_policy_and_safe_stepper_descriptors(tmp_path):
    from community_base.homework_steps.coursework import coursework_assignment

    root = fixture(tmp_path)
    assert sync(root).status == SyncStatus.SUCCESS
    homework = Homework.objects.get(source_content_id=UNIT_ID)
    homework.state = "OP"
    homework.save(update_fields=["state"])
    first, second = ordered_questions(homework)
    user = User.objects.create_user(email="scoring@example.invalid")
    assignment = coursework_assignment(homework, user)
    assert "Cargo" not in str(assignment.questions)
    assert assignment.question_results is None

    submission = submit_homework(
        homework, user, answers_by_question_id={first.pk: "2", second.pk: "Cargo"}
    )
    assert submission.questions_score == 3
    assert list(submission.answers.values_list("is_correct", flat=True)) == [True, True]
    assert coursework_assignment(homework, user).question_results is None
    homework.state = "SC"
    homework.save(update_fields=["state"])
    revealed = coursework_assignment(homework, user).question_results
    assert revealed["first"].correct_answer == "Beta"
    assert revealed["second"].correct_answer == "Cargo"


@pytest.mark.django_db
def test_unmanaged_questions_follow_authored_ones_and_legacy_order_is_unchanged(tmp_path):
    root = fixture(tmp_path)
    assert sync(root).status == SyncStatus.SUCCESS
    authored = Homework.objects.get(source_content_id=UNIT_ID)
    extra = Question.objects.create(
        homework=authored, text="Optional", question_type="FF", answer_type="ANY"
    )
    assert [item.source_question_id for item in ordered_questions(authored)] == [
        "first",
        "second",
        None,
    ]
    assert list(ordered_questions(authored))[-1].pk == extra.pk
    legacy = Homework.objects.get(slug="core")
    assert list(ordered_questions(legacy).values_list("pk", flat=True)) == list(
        legacy.questions.order_by("pk").values_list("pk", flat=True)
    )


@pytest.mark.django_db
def test_question_stable_id_swap_reserves_content_identities_before_fallback(tmp_path):
    root = fixture(tmp_path)
    assert sync(root).status == SyncStatus.SUCCESS
    first = Question.objects.get(source_content_id=FIRST_ID)
    second = Question.objects.get(source_content_id=SECOND_ID)
    path = root / SOURCE
    path.write_text(
        path.read_text()
        .replace("id: first", "id: temporary")
        .replace("id: second", "id: first")
        .replace("id: temporary", "id: second")
    )

    assert sync(root).status == SyncStatus.SUCCESS
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.source_question_id == "second"
    assert second.source_question_id == "first"
    assert Question.objects.filter(homework=first.homework).count() == 2


@pytest.mark.django_db
def test_self_paced_binding_explicit_null_clears_source_due_date(tmp_path):
    root = fixture(tmp_path)
    second = root / "cohorts/self-paced"
    second.mkdir()
    (second / "cohort.yaml").write_text(
        "content_id: 9a2b3c4d-0004-4000-8000-000000000009\n"
        "title: Self-paced quiz\n"
        "delivery: self_paced\n"
        "modules:\n  - core\n"
        f"homework:\n  - module: core\n    unit: {UNIT_ID}\n    due_at: null\n"
    )

    assert sync(root).status == SyncStatus.SUCCESS
    live = Homework.objects.get(source_content_id=UNIT_ID, cohort__slug="2026")
    self_paced = Homework.objects.get(source_content_id=UNIT_ID, cohort__slug="self-paced")
    assert live.due_date is not None
    assert self_paced.due_date is None
