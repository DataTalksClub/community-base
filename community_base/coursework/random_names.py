"""Leaderboard display-name generation.

Ported from the donor ``courses/random_names.py``. The donor generates
``"<adjective> <famous person>"`` from bundled word lists so leaderboard rows
are pseudonymous by default; the word lists are site data, so the package
default generator is a plain fallback and sites override
``COURSEWORK_DISPLAY_NAME_GENERATOR``.
"""

from community_base.coursework.hooks import hooks as coursework_hooks


def ensure_display_name(enrollment, generator=None):
    """Fill a blank leaderboard name in place; returns the display name.

    Mirrors the donor ``Enrollment.save()`` fill: a saved enrollment keeps
    the generated name, an unsaved one defers to the caller's save.
    """

    if enrollment.display_name:
        return enrollment.display_name
    generate = generator or coursework_hooks.display_name_generator
    enrollment.display_name = generate(enrollment)
    if enrollment.pk:
        enrollment.save(update_fields=["display_name"])
    return enrollment.display_name
