"""Which per-question results a stepper page may show, and where.

Results describe the learner's accepted answers, so they appear only beside those answers: on a
review whose accepted snapshot is primary. A host that has not revealed its results passes
``Assignment.question_results=None`` and nothing is shown.
"""


def revealed_results(assignment, *, accepted_primary: bool) -> dict:
    if not accepted_primary or not assignment.question_results:
        return {}
    return dict(assignment.question_results)


def attach_results(rows: list[dict], results: dict) -> list[dict]:
    for row in rows:
        row["result"] = results.get(row["key"])
    return rows


def result_for(results: dict, question):
    if question is None:
        return None
    return results.get(question.key)
