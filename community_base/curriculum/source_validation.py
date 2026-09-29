"""Use the import readers for the course format's semantic diagnostics."""

import re

from community_base.content_sync.documents import Diagnostic
from community_base.curriculum.parsers import course_collections, parse_course
from community_base.curriculum.source import CurriculumParseError

LOCATED = re.compile(r"^(?P<path>[^:]+):(?P<pointer>/[^:]*): \[(?P<rule>[^]]+)\] (?P<message>.*)$")


def course_source_diagnostics(result):
    from community_base.coursework.manifests import read_cohort_homework

    found = []
    for collection in course_collections(result):
        if _has_read_errors(result, collection):
            continue
        authored = []
        for document in result.documents:
            if document.collection.index != collection.index:
                continue
            if document.part.name == "homework_unit":
                authored.append(document)
        if not authored:
            continue
        try:
            parsed = parse_course(result, collection)
            read_cohort_homework(result, collection, parsed)
        except CurriculumParseError as error:
            found.append(_diagnostic(collection, str(error)))
    return found


def _has_read_errors(result, collection):
    for error in result.errors:
        if not collection.path or error.path.startswith(f"{collection.path}/"):
            return True
        if error.path == "content.yaml":
            return True
    return False


def _diagnostic(collection, message):
    match = LOCATED.match(message)
    if match:
        return Diagnostic(**match.groupdict())
    path = collection.path or "."
    return Diagnostic(path=path, pointer="/", rule="3.8", message=message)
