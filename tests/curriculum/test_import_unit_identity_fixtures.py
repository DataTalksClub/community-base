"""Valid leaf-module graphs and learner rows for importer identity regressions."""

from dataclasses import replace
from uuid import UUID

from django.contrib.auth import get_user_model
from django.utils import timezone

from community_base.coursework.models import Answer, Homework, Question, Submission
from community_base.curriculum.importing import apply_curriculum_graph
from community_base.curriculum.models import Cohort, Enrollment, UnitProgress
from community_base.curriculum.source import CourseGraph, ModuleGraph, ParsedCurriculum, UnitGraph
from tests.curriculum.utils import make_source


class MemoryCheckout:
    def read_bytes(self, path):
        return b"Unchanged authored content"


def identity(number):
    return str(UUID(int=number))


def unit_graph(number=10, slug="lesson", **changes):
    unit = UnitGraph(identity(number), slug, "Lesson", f"first/{slug}.md", body="Same body")
    return replace(unit, **changes)


def module_graph(number, units=(), **changes):
    module = ModuleGraph(identity(number), f"module-{number}", "Module", f"{number}/module.yaml")
    return replace(module, units=tuple(units), **changes)


def parsed_graph(modules, **changes):
    course = CourseGraph(identity(1), "course", "Course", "course.yaml", modules=tuple(modules))
    return ParsedCurriculum("identity-test", 1, "a" * 40, replace(course, **changes))


def apply_graph(graph, source=None):
    if source is None:
        source = make_source()
    return apply_curriculum_graph(graph, source, MemoryCheckout())


def learner_rows(unit):
    user = get_user_model().objects.create_user(email="learner@example.invalid")
    cohort = Cohort.objects.create(course=unit.module.course, slug="cohort", title="Cohort")
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    progress = UnitProgress.objects.create(user=user, unit=unit, completed_at=timezone.now())
    homework = Homework.objects.create(
        cohort=cohort,
        module=unit.module,
        unit=unit,
        slug="work",
        title="Work",
        due_date=timezone.now(),
    )
    question = Question.objects.create(homework=homework, text="Answer?", question_type="FF")
    submission = Submission.objects.create(
        homework=homework, enrollment=enrollment, student=user, total_score=7
    )
    answer = Answer.objects.create(
        submission=submission, question=question, answer_text="Preserved", is_correct=True
    )
    return progress, homework, question, submission, answer
