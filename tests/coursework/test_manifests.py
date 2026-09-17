"""Homework manifests bound from a cohort (`FORMAT.md` section 3.8, issue C7.11).

The reader half needs no database: it turns the course parser's
``CohortGraph.homework_bindings`` into homework graphs, and every rule it owns
is a located error naming the file, the pointer and the rule. The importer half
writes the rows through the one course sync, so what is asserted below is what
a repository push would produce.
"""

import base64
import json
import shutil

import pytest
from django.urls import include, path

from community_base.accounts.models import User
from community_base.content_sync.models import ContentSource
from community_base.content_sync.orchestration import sync_content_source
from community_base.coursework.answer_resolution import resolve_correct_answer
from community_base.coursework.manifests import HomeworkManifestError, read_cohort_homework
from community_base.coursework.models import (
    AnswerTypes,
    Homework,
    HomeworkState,
    Question,
    QuestionTypes,
)
from community_base.curriculum.models import Course, Unit
from community_base.curriculum.parsers import (
    course_collections,
    parse_course,
    parse_course_repository,
    read_courses,
)
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.utils import DTC_REPO

urlpatterns = [
    path("courses/", include("community_base.coursework.urls")),
    path("courses/", include("community_base.curriculum.urls")),
]


@pytest.fixture(autouse=True)
def course_parser():
    """The one course parser, registered as the sync registers it."""

    from community_base.content_sync import parsers
    from community_base.curriculum.apps import CONTENT_TYPE
    from community_base.curriculum.content_sync_parsers import CourseParser

    parsers._clear()
    parsers.register_parser(CONTENT_TYPE, CourseParser())
    yield
    parsers._clear()


MANIFEST = "cohorts/2026/homework/core/homework.yaml"
COHORT = "cohorts/2026/cohort.yaml"
HOMEWORK_UNIT_ID = "9a2b3c4d-0003-4000-8000-000000000002"


def copy(tmp_path, name="course"):
    target = tmp_path / name
    shutil.copytree(DTC_REPO, target)
    return target


def edit(root, relative, old, new):
    path = root / relative
    text = path.read_text()
    assert old in text, f"{relative} does not contain {old!r}"
    path.write_text(text.replace(old, new))


def graphs(root):
    result = read_courses(root)
    collection = course_collections(result)[0]
    return read_cohort_homework(result, collection, parse_course(result, collection))


def keyring_json() -> str:
    return json.dumps(
        {"active_key_id": "k1", "keys": {"k1": base64.b64encode(bytes(range(32))).decode()}}
    )


def sync(slug="dtc-repo", repo="DataTalksClub/ml-zoomcamp", repo_dir=DTC_REPO):
    source = ContentSource.objects.filter(slug=slug).first()
    if source is None:
        source = ContentSource(slug=slug, repo_name=repo, webhook_secret="fixture-secret")
        source.full_clean()
        source.save()
    return sync_content_source(source, repo_dir=str(repo_dir))


# --------------------------------------------------------------------------
# The reader: bindings onto graphs
# --------------------------------------------------------------------------


def test_a_binding_reads_the_manifest_it_points_at():
    found = graphs(DTC_REPO)

    assert len(found) == 1
    homework = found[0]
    assert homework.source_path == MANIFEST
    assert (homework.cohort_slug, homework.module_slug) == ("2026", "core")
    assert homework.slug == "core"
    assert homework.title == "Introduction homework"
    assert homework.unit_content_id == HOMEWORK_UNIT_ID
    assert homework.initial_state == "closed"
    assert homework.due_at.isoformat() == "2026-09-21T23:59:00+00:00"
    assert homework.instructions_source_path == "cohorts/2026/homework/core/homework.md"
    assert homework.instructions_markdown.strip() == "Submit the notebook."


def test_the_questions_carry_their_options_answer_types_and_sealed_answers():
    homework = graphs(DTC_REPO)[0]

    choice, free_form = homework.questions
    assert (choice.stable_id, choice.type, choice.points) == ("q1", "multiple_choice", 1)
    assert [(option.id, option.label) for option in choice.options] == [
        ("col", "A column"),
        ("row", "A row"),
    ]
    assert choice.answer_type is None
    assert choice.answer["key_id"] == "k1"
    assert (free_form.stable_id, free_form.type, free_form.answer_type) == (
        "q2",
        "free_form",
        "integer",
    )
    assert free_form.options == ()
    assert set(free_form.answer) == {
        "version",
        "algorithm",
        "kdf",
        "key_id",
        "salt",
        "nonce",
        "ciphertext",
        "context_sha256",
    }


def test_a_binding_pointing_at_a_manifest_that_does_not_exist_is_located(tmp_path):
    root = copy(tmp_path)
    edit(root, COHORT, "source: homework/core/homework.yaml", "source: homework/gone/homework.yaml")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    message = str(error.value)
    assert COHORT in message
    assert "/homework/0/source" in message
    assert "[3.8]" in message
    assert "cohorts/2026/homework/gone/homework.yaml" in message


def test_a_binding_climbing_out_of_its_cohort_directory_is_rejected(tmp_path):
    root = copy(tmp_path)
    edit(root, COHORT, "source: homework/core/homework.yaml", "source: ../2024/homework.yaml")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    assert "outside the cohort directory" in str(error.value)


def test_a_binding_naming_a_module_the_cohort_does_not_place_is_rejected(tmp_path):
    root = copy(tmp_path)
    # `advanced` is a module of the course; the 2026 cohort places `core` alone.
    edit(root, COHORT, "  - module: core", "  - module: advanced")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    message = str(error.value)
    assert COHORT in message
    assert "/homework/0/module" in message
    assert "does not place the module 'advanced'" in message


def test_a_binding_whose_unit_is_not_a_homework_unit_is_rejected(tmp_path):
    root = copy(tmp_path)
    edit(root, "01-core/02-homework.md", "kind: homework\n", "")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    message = str(error.value)
    assert "/homework/0/unit" in message
    assert "is a lesson unit" in message


def test_a_binding_whose_unit_is_unknown_is_rejected(tmp_path):
    root = copy(tmp_path)
    edit(root, COHORT, HOMEWORK_UNIT_ID, "9a2b3c4d-9999-4000-8000-000000000009")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    assert "no unit of this course carries the content_id" in str(error.value)


def test_a_missing_instructions_file_is_located(tmp_path):
    root = copy(tmp_path)
    (root / "cohorts/2026/homework/core/homework.md").unlink()

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    message = str(error.value)
    assert MANIFEST in message
    assert "/instructions_path" in message


# --------------------------------------------------------------------------
# No plaintext answer shape is read anywhere
# --------------------------------------------------------------------------


def test_a_plaintext_correct_answer_is_rejected_with_the_file_and_key_named(tmp_path):
    root = copy(tmp_path)
    edit(root, MANIFEST, "    points: 1\n", "    points: 1\n    correct: A column\n")

    with pytest.raises(CurriculumParseError) as error:
        parse_course_repository(root)

    message = str(error.value)
    assert MANIFEST in message
    assert "/questions/0/correct" in message
    assert "unknown key: correct" in message


def test_an_envelope_sealed_for_another_question_is_rejected(tmp_path):
    root = copy(tmp_path)
    edit(root, MANIFEST, "    id: q1\n", "    id: q9\n")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    message = str(error.value)
    assert "/questions/0/answer" in message
    assert "context does not match" in message


def test_a_choice_question_is_answered_by_its_options_not_an_answer_type(tmp_path):
    root = copy(tmp_path)
    edit(root, MANIFEST, "    points: 1\n", "    points: 1\n    answer_type: integer\n")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    assert "/questions/0/answer_type" in str(error.value)


def test_a_free_form_question_without_an_answer_type_is_rejected(tmp_path):
    root = copy(tmp_path)
    edit(root, MANIFEST, "    answer_type: integer\n", "")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    assert "/questions/1/answer_type" in str(error.value)


def test_an_answer_type_any_question_carries_no_answer(tmp_path):
    root = copy(tmp_path)
    edit(root, MANIFEST, "    answer_type: integer\n", "    answer_type: any\n")

    with pytest.raises(HomeworkManifestError) as error:
        graphs(root)

    message = str(error.value)
    assert "/questions/1/answer" in message
    assert "is not scored" in message


# --------------------------------------------------------------------------
# The importer: rows, idempotence and the unit page
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_bound_manifest_creates_the_homework_its_questions_and_their_answers():
    sync()

    course = Course.objects.get(slug="ml-zoomcamp")
    homework = Homework.objects.get(cohort__course=course, slug="core")
    assert homework.cohort.slug == "2026"
    assert homework.module.slug == "core"
    assert homework.unit.slug == "homework"
    assert homework.title == "Introduction homework"
    assert homework.state == HomeworkState.CLOSED.value
    assert homework.due_date.isoformat() == "2026-09-21T23:59:00+00:00"
    assert homework.instructions_markdown.strip() == "Submit the notebook."
    assert homework.instructions_source_path == "cohorts/2026/homework/core/homework.md"
    assert homework.source_path == MANIFEST
    assert str(homework.source_content_id) == "9a2b3c4d-0005-4000-8000-000000000001"

    choice, free_form = homework.questions.order_by("source_question_id")
    assert choice.question_type == QuestionTypes.MULTIPLE_CHOICE.value
    assert choice.possible_answers == "A column\nA row"
    assert choice.source_option_ids == ["col", "row"]
    assert choice.answer_type is None
    assert choice.scores_for_correct_answer == 1
    assert choice.correct_answer is None
    assert choice.answer_envelope["algorithm"] == "A256GCM"
    assert free_form.question_type == QuestionTypes.FREE_FORM.value
    assert free_form.answer_type == AnswerTypes.INTEGER.value
    assert free_form.possible_answers is None
    assert free_form.source_option_ids is None
    assert free_form.scores_for_correct_answer == 2


@pytest.mark.django_db
def test_the_form_keys_come_from_the_manifest_and_default_to_the_field_default():
    sync()

    homework = Homework.objects.get(slug="core")
    assert homework.homework_url_field is True
    assert homework.learning_in_public_cap == 3
    # Absent form keys keep the model's own defaults rather than a second set.
    assert homework.time_spent_lectures_field is True
    assert homework.faq_contribution_field is True


@pytest.mark.django_db
def test_the_imported_envelopes_decrypt_to_the_authored_answers(settings):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_ANSWER_KEYRING": keyring_json(),
    }
    sync()

    choice, free_form = Homework.objects.get(slug="core").questions.order_by("source_question_id")
    assert resolve_correct_answer(choice) == "1"
    assert resolve_correct_answer(free_form) == "42"


@pytest.mark.django_db
def test_re_import_leaves_every_row_count_unchanged():
    sync()
    before = (Homework.objects.count(), Question.objects.count())
    homework = Homework.objects.get(slug="core")
    # An operator opened the homework after the first import.
    homework.state = HomeworkState.OPEN.value
    homework.save(update_fields=["state"])

    log = sync()

    assert log.items_created == 0
    assert (Homework.objects.count(), Question.objects.count()) == before
    homework.refresh_from_db()
    # `initial_state` is the state a homework is created in, not one restored.
    assert homework.state == HomeworkState.OPEN.value


@pytest.mark.django_db
def test_a_manifest_the_cohort_stopped_binding_is_removed(tmp_path):
    sync()
    root = copy(tmp_path)
    edit(root, COHORT, "homework:\n  - module: core\n", "")
    edit(root, COHORT, "    source: homework/core/homework.yaml\n", "")
    edit(root, COHORT, f"    unit: {HOMEWORK_UNIT_ID}\n", "")

    sync(repo_dir=root)

    assert not Homework.objects.filter(slug="core").exists()
    assert not Question.objects.exists()


@pytest.mark.django_db
def test_a_binding_with_a_unit_renders_the_submission_form_on_that_unit_page(settings, client):
    settings.ROOT_URLCONF = __name__
    sync()
    unit = Unit.objects.get(source_content_id=HOMEWORK_UNIT_ID)
    homework = Homework.objects.get(slug="core")
    homework.state = HomeworkState.OPEN.value
    homework.save(update_fields=["state"])
    client.force_login(User.objects.create_user(email="learner@example.com"))

    response = client.get("/courses/ml-zoomcamp/2026/core/homework/")

    assert response.status_code == 200
    body = response.content.decode()
    assert unit.title in body
    assert "Introduction homework" in body
    assert "What is a feature?" in body
    # One form and one POST handler: the unit page posts to the homework view.
    assert 'action="/courses/ml-zoomcamp/2026/homework/core/"' in body
    assert f'name="answer_{homework.questions.first().pk}"' in body


@pytest.mark.django_db
def test_a_unit_nobody_bound_shows_no_submission_form(settings, client):
    settings.ROOT_URLCONF = __name__
    sync()

    response = client.get("/courses/ml-zoomcamp/2026/core/lesson/")

    assert response.status_code == 200
    assert "What is a feature?" not in response.content.decode()
