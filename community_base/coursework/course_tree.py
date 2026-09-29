"""Course-tree homework units bound explicitly to cohort assignments."""

from __future__ import annotations

import math

from community_base.coursework.manifests import (
    HomeworkGraph,
    HomeworkManifestError,
    HomeworkQuestionGraph,
    _answer_type,
    _due_at,
    _form,
    _options,
)

RULE = "3.8"


def read_course_tree_binding(
    result, cohort, binding, index, sources, placed, units, modules, source_questions
):
    where = cohort.source_path or cohort.slug
    pointer = f"/homework/{index}"
    module_slug = binding.get("module")
    if module_slug not in placed:
        raise HomeworkManifestError(
            f"{where}:{pointer}/module: [{RULE}] cohort does not place {module_slug!r}"
        )
    identity = str(binding.get("unit"))
    document = sources.get(identity)
    if document is None or identity not in units:
        raise HomeworkManifestError(
            f"{where}:{pointer}/unit: [{RULE}] no authored homework unit "
            f"with content_id {identity!r}"
        )
    _check_module(where, pointer, module_slug, document.raw.path, modules)
    due_at = _binding_due_date(where, pointer, cohort, binding, document)
    graph = _source_graph(
        result, cohort, binding, document, module_slug, due_at, source_questions[identity]
    )
    _validate_stepper_binding(graph, where, pointer)
    return graph


def _validate_stepper_binding(graph, where, pointer):
    cap = graph.form.learning_in_public_cap
    if cap is None:
        cap = 7
    if cap < 0:
        raise HomeworkManifestError(
            f"{where}:{pointer}/form/learning_in_public_cap: [{RULE}] cap cannot be negative"
        )
    if graph.stepper and cap:
        if any(question.stable_id == "learning-in-public" for question in graph.questions):
            raise HomeworkManifestError(
                f"{where}:{pointer}/unit: [{RULE}] learning-in-public is reserved by the stepper"
            )


def _source_graph(result, cohort, binding, document, module_slug, due_at, questions):
    identity = document.content_id
    source_form = document.values.get("form") or {}
    bound_form = binding.get("form") or {}
    instructions = document.raw.path.rsplit("/", 1)[0] + "/homework.md"
    return HomeworkGraph(
        content_id=identity,
        slug=document.slug,
        title=document.title,
        source_path=document.raw.path,
        cohort_slug=cohort.slug,
        module_slug=module_slug,
        unit_content_id=identity,
        instructions_source_path=instructions,
        instructions_markdown=result.repository.read_text(instructions),
        due_at=due_at,
        initial_state=binding.get("initial_state")
        or document.values.get("initial_state")
        or "closed",
        form=_form({**source_form, **bound_form}),
        questions=questions,
        course_tree=True,
        stepper=document.values.get("stepper", False),
    )


def _check_module(where, pointer, slug, source_path, modules):
    for module in modules:
        if module.slug != slug:
            continue
        directory = module.source_path.rsplit("/", 1)[0]
        if source_path.startswith(f"{directory}/"):
            return
    raise HomeworkManifestError(
        f"{where}:{pointer}/module: [{RULE}] authored unit {source_path!r} "
        f"does not belong to top-level module {slug!r}"
    )


def _binding_due_date(where, pointer, cohort, binding, document):
    if "due_at" in binding:
        value = binding["due_at"]
    else:
        value = document.values.get("due_at")
    if value is None:
        if cohort.mode == "cohort":
            raise HomeworkManifestError(
                f"{where}:{pointer}/due_at: [{RULE}] live homework needs a source or binding due_at"
            )
        return None
    return _due_at(value)


def validate_source_unit(document):
    cap = (document.values.get("form") or {}).get("learning_in_public_cap")
    if cap is not None and cap < 0:
        raise HomeworkManifestError(
            f"{document.raw.path}:/form/learning_in_public_cap: [{RULE}] cap cannot be negative"
        )
    found = []
    seen_ids = set()
    seen_content_ids = set()
    for index, entry in enumerate(document.values.get("questions") or ()):
        question = _question(document.raw.path, index, entry)
        if question.stable_id in seen_ids or question.content_id in seen_content_ids:
            raise HomeworkManifestError(
                f"{document.raw.path}:/questions/{index}: [{RULE}] duplicate question identity"
            )
        seen_ids.add(question.stable_id)
        seen_content_ids.add(question.content_id)
        found.append(question)
    if not found:
        raise HomeworkManifestError(
            f"{document.raw.path}:/questions: [{RULE}] homework needs at least one question"
        )
    if document.values.get("stepper") and cap != 0:
        if "learning-in-public" in seen_ids:
            raise HomeworkManifestError(
                f"{document.raw.path}:/questions: [{RULE}] "
                "learning-in-public is reserved by the stepper"
            )
    return tuple(found)


def _question(path, index, entry):
    pointer = f"/questions/{index}"
    question_type = entry["type"]
    options = _options(path, pointer, entry, question_type)
    _validate_options(path, pointer, options)
    answer_type = _answer_type(path, pointer, entry, question_type)
    correct = _correct(path, pointer, entry, question_type, answer_type, options)
    if entry["points"] < 0:
        raise HomeworkManifestError(f"{path}:{pointer}/points: [{RULE}] points cannot be negative")
    return HomeworkQuestionGraph(
        content_id=entry["content_id"],
        stable_id=entry["id"],
        type=question_type,
        prompt=entry["prompt"],
        points=entry["points"],
        options=options,
        answer_type=answer_type,
        correct=correct,
        authored_position=index,
        step_label=entry.get("step_label") or "",
    )


def _correct(path, pointer, entry, question_type, answer_type, options):
    correct = entry.get("correct")
    if answer_type == "any":
        if correct is not None:
            raise HomeworkManifestError(
                f"{path}:{pointer}/correct: [{RULE}] answer_type: any has no correct answer"
            )
        return None
    if correct is None or correct == "":
        raise HomeworkManifestError(
            f"{path}:{pointer}/correct: [{RULE}] a scored question needs correct"
        )
    if question_type in ("multiple_choice", "checkboxes"):
        _validate_indices(path, pointer, correct, question_type, len(options))
    if answer_type == "integer":
        _validate_number(path, pointer, correct, integer=True)
    if answer_type == "float":
        _validate_number(path, pointer, correct, integer=False)
    return correct


def _validate_options(path, pointer, options):
    labels = set()
    for option in options:
        label = option.label.strip()
        if not label or "\n" in label or label in labels:
            raise HomeworkManifestError(
                f"{path}:{pointer}/options: [{RULE}] choice labels must be distinct single lines"
            )
        labels.add(label)


def _validate_number(path, pointer, correct, *, integer):
    try:
        if integer:
            value = int(correct)
        else:
            value = float(correct)
    except ValueError:
        raise HomeworkManifestError(
            f"{path}:{pointer}/correct: [{RULE}] answer is not a valid number"
        ) from None
    if not integer and not math.isfinite(value):
        raise HomeworkManifestError(f"{path}:{pointer}/correct: [{RULE}] answer must be finite")


def _validate_indices(path, pointer, correct, question_type, option_count):
    parts = correct.split(",")
    if question_type == "multiple_choice" and len(parts) != 1:
        _invalid_correct(path, pointer)
    positions = set()
    for part in parts:
        if not part.isascii() or not part.isdecimal():
            _invalid_correct(path, pointer)
        position = int(part)
        if position < 1 or position > option_count or position in positions:
            _invalid_correct(path, pointer)
        positions.add(position)


def _invalid_correct(path, pointer):
    raise HomeworkManifestError(
        f"{path}:{pointer}/correct: [{RULE}] expected unique one-based choice indices"
    )
