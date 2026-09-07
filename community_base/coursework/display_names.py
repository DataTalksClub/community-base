"""Enrollment leaderboard display-name defaulting.

The donor fills a blank ``Enrollment.display_name`` inside ``save()`` with
``generate_random_name()`` from ``courses/random_names.py``. The package turns
that into an explicit service: ``ensure_display_name`` resolves the
``enrollment_display_name_generator`` hook (the ``generator`` argument wins)
and stores its result when it is a non-empty string. The generator is called
with the ``enrollment`` keyword, matching the package hook convention; the
discard default returns ``None`` and the name stays blank. The random-name
vocabulary stays a site concern — DTC passes its generator through the hook —
and existing names are never regenerated.
"""

from community_base.coursework.hooks import hooks
from community_base.curriculum.models import Enrollment


def ensure_display_name(enrollment: Enrollment, generator=None) -> str:
    if enrollment.display_name:
        return enrollment.display_name

    if generator is None:
        generator = hooks.enrollment_display_name_generator

    if callable(generator):
        generated = generator(enrollment=enrollment)
        if isinstance(generated, str) and generated:
            enrollment.display_name = generated
            enrollment.save(update_fields=["display_name"])

    return enrollment.display_name
