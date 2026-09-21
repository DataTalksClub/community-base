"""The `course` kind: course, module, unit, cohort and homework (section 3.8)."""

from __future__ import annotations

from community_base.content_sync.kinds.base import (
    SHAPE_DOCUMENT,
    SHAPE_MANIFEST,
    SHAPE_TREE,
    KeySpec,
    KindSpec,
    PartSpec,
)
from community_base.content_sync.kinds.layouts import CourseLayout

UNIT_KINDS = ("lesson", "homework", "event", "checklist_item")
DELIVERY_CHOICES = ("live", "self_paced")
HOMEWORK_STATES = ("closed", "open", "scored")
QUESTION_TYPES = ("multiple_choice", "checkboxes", "free_form", "free_form_long")
ANSWER_TYPES = ("any", "float", "integer", "exact_string", "contains_string")
FORM_FLAGS = ("homework_url", "time_spent_lectures", "time_spent_homework", "faq_contribution")

COURSE = PartSpec(
    name="course",
    shape=SHAPE_MANIFEST,
    keys={
        "description": KeySpec("markdown", required=True),
        "instructors": KeySpec("reference_list", reference_kind="person"),
        "default_unit_required_level": KeySpec("level"),
        "outcome": KeySpec("text", max_length=300),
        "prerequisites": KeySpec("text", max_length=1000),
        "discussion_url": KeySpec("url"),
        "repository_url": KeySpec("url"),
        "docs_url": KeySpec("url"),
        "faq_url": KeySpec("url"),
        "hashtag": KeySpec("hashtag"),
        "testimonials": KeySpec(
            "object_list",
            item_keys={
                "quote": KeySpec("string", required=True),
                "name": KeySpec("string"),
                "role": KeySpec("string"),
                "company": KeySpec("string"),
                "source_url": KeySpec("url"),
            },
        ),
    },
)

MODULE = PartSpec(
    name="module",
    shape=SHAPE_MANIFEST,
    keys={
        "is_bonus": KeySpec("boolean", default=False),
        "available_after_days": KeySpec("integer"),
    },
)

UNIT = PartSpec(
    name="unit",
    shape=SHAPE_DOCUMENT,
    keys={
        "kind": KeySpec("choice", choices=UNIT_KINDS, default="lesson"),
        "video_url": KeySpec("url"),
        "timestamps": KeySpec(
            "object_list",
            item_keys={
                "time": KeySpec("timestamp", required=True),
                "title": KeySpec("string"),
            },
        ),
        "session_position": KeySpec("integer"),
        "is_bonus": KeySpec("boolean", default=False),
        "code": KeySpec(
            "object_list",
            item_keys={
                "label": KeySpec("string"),
                "path": KeySpec("string", required=True),
            },
        ),
    },
)

COHORT = PartSpec(
    name="cohort",
    shape=SHAPE_MANIFEST,
    keys={
        "delivery": KeySpec("choice", choices=DELIVERY_CHOICES, required=True),
        "start_date": KeySpec("date"),
        "end_date": KeySpec("date"),
        "modules": KeySpec("slug_list"),
        # Decision D38: a mapping carrying an optional notice path, not a
        # boolean. Two of the seventeen real archived cohorts point their
        # notice at `cohorts/<year>/leaderboard.md` rather than `README.md`.
        "archive": KeySpec(
            "mapping", item_keys={"notice_path": KeySpec("string", default="README.md")}
        ),
        "registration_url": KeySpec("url"),
        "hashtag": KeySpec("hashtag"),
        "homework": KeySpec(
            "object_list",
            item_keys={
                "module": KeySpec("slug", required=True),
                "source": KeySpec("string", required=True),
                "unit": KeySpec("uuid"),
            },
        ),
    },
)

HOMEWORK = PartSpec(
    name="homework",
    shape=SHAPE_MANIFEST,
    keys={
        "instructions_path": KeySpec("string", default="homework.md"),
        "due_at": KeySpec("datetime", required=True),
        "initial_state": KeySpec("choice", choices=HOMEWORK_STATES, default="closed"),
        # Every form key is optional; an absent one takes the field default the
        # coursework model carries. `learning_in_public_cap` is the one that is
        # not a flag, so it is typed on its own.
        "form": KeySpec(
            "mapping",
            item_keys={
                **{name: KeySpec("boolean") for name in FORM_FLAGS},
                "learning_in_public_cap": KeySpec("integer"),
            },
        ),
        "questions": KeySpec(
            "object_list",
            required=True,
            item_keys={
                "content_id": KeySpec("uuid", required=True),
                "id": KeySpec("slug", required=True),
                "type": KeySpec("choice", choices=QUESTION_TYPES, required=True),
                "prompt": KeySpec("markdown", required=True),
                "points": KeySpec("integer", required=True),
                "options": KeySpec(
                    "object_list",
                    item_keys={
                        "id": KeySpec("slug", required=True),
                        "label": KeySpec("string", required=True),
                    },
                ),
                "answer_type": KeySpec("choice", choices=ANSWER_TYPES),
                # The envelope of `coursework/answer_crypto.py`, checked there
                # and nowhere else: a second field-by-field schema here would
                # be a second envelope validator.
                "answer": KeySpec("mapping"),
            },
        ),
    },
)

SPEC = KindSpec(
    name="course",
    shape=SHAPE_TREE,
    layout=CourseLayout(),
    parts={
        "course": COURSE,
        "module": MODULE,
        "unit": UNIT,
        "cohort": COHORT,
        "homework": HOMEWORK,
    },
    route=lambda path: f"courses/{path}",
)
