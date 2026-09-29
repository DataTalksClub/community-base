"""Reserve cohort-owned assignments before slug fallback and source moves."""

from uuid import uuid4

from community_base.coursework.manifests import HomeworkManifestError
from community_base.coursework.models import Homework
from community_base.curriculum.models import Cohort


class HomeworkImport:
    def __init__(self, course, graphs):
        self.cohorts = {cohort.slug: cohort for cohort in Cohort.objects.filter(course=course)}
        self.existing = list(Homework.objects.filter(cohort__course=course))
        self.by_identity = {}
        self.by_slug = {}
        for homework in self.existing:
            if homework.source_content_id is not None:
                key = (homework.cohort_id, str(homework.source_content_id))
                if key in self.by_identity:
                    raise HomeworkManifestError("ambiguous source homework identity in cohort")
                self.by_identity[key] = homework
            self.by_slug[(homework.cohort_id, homework.slug)] = homework
        self.reserved = self._reserved(graphs)
        self.plans = self._plan(graphs)
        self._park_conflicting_slugs(graphs)

    def _reserved(self, graphs):
        reserved = set()
        for graph in graphs:
            cohort = self.cohorts.get(graph.cohort_slug)
            if cohort is None:
                raise HomeworkManifestError(f"{graph.source_path}: no cohort {graph.cohort_slug!r}")
            homework = self.by_identity.get((cohort.pk, graph.content_id))
            if homework is not None:
                reserved.add(homework.pk)
        return reserved

    def _plan(self, graphs):
        plans = {}
        claimed = set()
        for graph in graphs:
            cohort = self.cohorts[graph.cohort_slug]
            homework = self.by_identity.get((cohort.pk, graph.content_id))
            if homework is None:
                candidate = self.by_slug.get((cohort.pk, graph.slug))
                if candidate is not None and candidate.pk not in self.reserved:
                    homework = candidate
            if homework is None:
                homework = Homework(cohort=cohort, slug=graph.slug)
            if homework.pk is not None and homework.pk in claimed:
                raise HomeworkManifestError(
                    f"{graph.source_path}: multiple bindings claim one assignment"
                )
            if homework.pk is not None:
                claimed.add(homework.pk)
            plans[id(graph)] = (cohort, homework)
        return plans

    def _park_conflicting_slugs(self, graphs):
        for graph in graphs:
            cohort, target = self.plans[id(graph)]
            occupant = self.by_slug.get((cohort.pk, graph.slug))
            if occupant is None or occupant.pk == target.pk:
                continue
            if occupant.source_content_id is None:
                raise HomeworkManifestError(
                    f"{graph.source_path}: occupied operator-managed assignment slug {graph.slug!r}"
                )
            occupant.slug = f"park-{uuid4().hex}"
            Homework.objects.filter(pk=occupant.pk).update(slug=occupant.slug)

    def resolve(self, graph):
        cohort, homework = self.plans[id(graph)]
        homework.source_content_id = graph.content_id
        return cohort, homework
