"""Reserve question identities before matching legacy slots or changing IDs."""

from uuid import uuid4

from community_base.coursework.manifests import HomeworkManifestError
from community_base.coursework.models import Question


class QuestionImport:
    def __init__(self, homework, graphs, source_path):
        self.homework = homework
        self.source_path = source_path
        self.existing = list(Question.objects.filter(homework=homework))
        self.by_content_id = {}
        self.by_stable_id = {}
        for question in self.existing:
            if question.source_content_id is not None:
                self.by_content_id[str(question.source_content_id)] = question
            if question.source_question_id:
                self.by_stable_id[question.source_question_id] = question
        incoming = {graph.content_id for graph in graphs}
        self.reserved = set()
        for question in self.existing:
            if question.source_content_id is None:
                continue
            if str(question.source_content_id) in incoming:
                self.reserved.add(question.pk)
        self.plans = self._plan(graphs)
        self._park_conflicting_ids(graphs)

    def _plan(self, graphs):
        plans = {}
        claimed = set()
        for index, graph in enumerate(graphs):
            question = self.by_content_id.get(graph.content_id)
            if question is None:
                candidate = self.by_stable_id.get(graph.stable_id)
                if candidate is not None and candidate.pk not in self.reserved:
                    question = candidate
            if question is None:
                question = Question(homework=self.homework)
            if question.pk is not None and question.pk in claimed:
                raise HomeworkManifestError(
                    f"{self.source_path}:/questions/{index}: [3.8] "
                    "multiple identities claim one existing question"
                )
            if question.pk is not None:
                claimed.add(question.pk)
            plans[graph.content_id] = question
        return plans

    def _park_conflicting_ids(self, graphs):
        to_park = {}
        for graph in graphs:
            occupant = self.by_stable_id.get(graph.stable_id)
            target = self.plans[graph.content_id]
            if occupant is not None and occupant.pk != target.pk:
                to_park[occupant.pk] = occupant
        for question in to_park.values():
            question.source_question_id = f"park-{uuid4().hex}"
            Question.objects.filter(pk=question.pk).update(
                source_question_id=question.source_question_id
            )

    def resolve(self, graph):
        question = self.plans[graph.content_id]
        question.source_content_id = graph.content_id
        return question
