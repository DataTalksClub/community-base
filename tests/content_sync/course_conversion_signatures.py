"""Shared parsed semantic signature for canonical conversion regressions."""

from community_base.content_sync.rendering import render_document
from community_base.coursework.manifests import read_cohort_homework
from community_base.curriculum.parsers import parse_course_repository, read_courses
from community_base.curriculum.source import ModuleGraph


def _tree(module, parent="course"):
    rows = [
        (
            "module",
            parent,
            module.content_id,
            module.slug,
            module.title,
            module.sort_order,
            module.source_path,
            module.overview,
            module.syllabus_section,
            module.is_bonus,
        )
    ]
    for sibling in module.siblings:
        if isinstance(sibling, ModuleGraph):
            rows.extend(_tree(sibling, module.content_id))
            continue
        rows.append(_unit_row(module, sibling))
    return rows


def _unit_row(module, unit):
    # The existing front-matter writer adds one separator newline.
    return (
        "unit",
        module.content_id,
        unit.content_id,
        unit.slug,
        unit.title,
        unit.sort_order,
        unit.source_path,
        unit.body.removeprefix("\n"),
        render_document(unit.body, unit.title).html,
        unit.kind,
        unit.is_bonus,
        unit.source_sibling_position,
    )


def _question(question):
    options = [(option.id, option.label) for option in question.options]
    return (
        question.content_id,
        question.stable_id,
        question.type,
        question.prompt,
        question.points,
        options,
        question.correct,
        question.step_label,
    )


def course_signature(root):
    parsed = parse_course_repository(root)
    modules = parsed.course.modules
    tree = []
    for module in modules:
        tree.extend(_tree(module))
    result = read_courses(root)
    homework = read_cohort_homework(result, result.collections[0], parsed)
    assignment = homework[0]
    policy = (
        assignment.content_id,
        assignment.slug,
        assignment.title,
        assignment.source_path,
        assignment.unit_content_id,
        assignment.cohort_slug,
        assignment.module_slug,
        assignment.due_at,
        assignment.initial_state,
        assignment.form,
        assignment.instructions_source_path,
        assignment.instructions_markdown,
        assignment.course_tree,
    )
    questions = [_question(item) for item in assignment.questions]
    return tree, modules[0].syllabus_section, modules[0].is_bonus, policy, questions
