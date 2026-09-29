"""One question ordering rule for legacy and authored assignments."""

from django.db.models import F


def ordered_questions(homework):
    """Authored rows first; unmanaged rows keep PK order on every database."""

    return homework.questions.order_by(F("authored_position").asc(nulls_last=True), "id")
