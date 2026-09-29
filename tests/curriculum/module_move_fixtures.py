"""Valid two-level graphs and learner rows for module move regressions."""

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth import get_user_model
from django.utils import timezone

from community_base.coursework.models import Answer, Homework, Question, Submission
from community_base.curriculum.importing import apply_curriculum_graph
from community_base.curriculum.models import Enrollment, UnitProgress
from community_base.curriculum.source import (
    CohortGraph,
    CourseGraph,
    ModuleGraph,
    ParsedCurriculum,
    UnitGraph,
    validate_module_tree,
)
from tests.curriculum.utils import checkout, make_source


def identity(name):
    return str(uuid5(NAMESPACE_URL, f"module-move/{name}"))


def module(slug, *, children=(), units=(), sort_order=1):
    return ModuleGraph(
        content_id=identity(slug),
        slug=slug,
        title=slug,
        source_path=f"{slug}/module.yaml",
        children=children,
        units=units,
        sort_order=sort_order,
    )


LESSON = UnitGraph(identity("lesson"), "lesson", "Lesson", "lesson.md", body="Keep this.")
TOPIC = module("topic", units=(LESSON,))
COHORT = CohortGraph(identity("cohort"), "self-paced", "Self-paced", mode="self_paced")


def write_module(root, graph, parent_path=""):
    path = f"{parent_path}{graph.slug}/"
    source_path = f"{path}module.yaml"
    target = root / source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(graph.title)
    units = []
    for unit in graph.units:
        unit_path = f"{path}{unit.slug}.md"
        (root / unit_path).write_text(unit.body)
        units.append(replace(unit, source_path=unit_path))
    children = tuple(write_module(root, child, path) for child in graph.children)
    return replace(graph, source_path=source_path, units=tuple(units), children=children)


def apply_tree(root, modules, *, cohort=COHORT, course_slug="course", title="Course"):
    validate_module_tree(modules, where="module-move fixture")
    modules = tuple(write_module(root, graph) for graph in modules)
    (root / "course.yaml").write_text(title)
    course = CourseGraph(
        identity(course_slug),
        course_slug,
        title,
        "course.yaml",
        modules=modules,
        cohorts=(cohort,),
    )
    parsed = ParsedCurriculum("module-move-fixture-v1", 1, None, course)
    with checkout(root) as active:
        return apply_curriculum_graph(parsed, make_source(), active)


def learner_rows(module):
    unit = module.units.get()
    cohort = module.course.cohorts.get()
    user = get_user_model().objects.create()
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    progress = UnitProgress.objects.create(user=user, unit=unit, completed_at=timezone.now())
    homework = Homework.objects.create(
        cohort=cohort,
        module=module,
        unit=unit,
        slug="homework",
        title="Keep homework",
        instructions_markdown="Instructions",
        state="SC",
    )
    return (enrollment, progress, homework, *homework_answers(homework, user, enrollment))


def homework_answers(homework, user, enrollment):
    question = Question.objects.create(
        homework=homework,
        text="Question",
        question_type="FF",
        answer_type="INT",
        correct_answer="42",
        scores_for_correct_answer=3,
    )
    submission = Submission.objects.create(
        homework=homework,
        student=user,
        enrollment=enrollment,
        questions_score=3,
        total_score=3,
        problems_comments="Keep comments",
    )
    answer = Answer.objects.create(
        submission=submission,
        question=question,
        answer_text="42",
        is_correct=True,
    )
    return (question, submission, answer)


def snapshot(rows):
    return [type(row).objects.values().get(pk=row.pk) for row in rows]
