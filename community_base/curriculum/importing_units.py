"""Plan course-wide unit identities before atomically applying module moves."""

from uuid import UUID, uuid4

from community_base.curriculum.models import Module, Unit
from community_base.curriculum.source import CurriculumParseError


def _identity(value):
    if value is None:
        return None
    return UUID(str(value))


class UnitImport:
    """Reserve final unit slots before writes, independent of traversal order."""

    def __init__(self, course, modules):
        self.course = course
        self.by_identity = {}
        self.by_slot = {}
        self.plans = {}
        self.destinations = {}
        self.parked = {}
        self.seen = set()
        self.visited_modules = set()
        self._index_units()
        self.module_identities, self.module_slots = self._index_modules()
        entries = list(self._entries(modules))
        reserved = self._reserve_identities(entries)
        self._plan(entries, reserved)
        self._check_occupants()

    def _index_units(self):
        for unit in Unit.objects.filter(module__course_id=self.course.pk):
            self.by_slot[(unit.module_id, unit.slug)] = unit
            identity = unit.source_content_id
            if identity is None:
                continue
            if identity in self.by_identity:
                raise CurriculumParseError(f"ambiguous unit content_id {identity} in course")
            self.by_identity[identity] = unit

    def _entries(self, modules, parent=None, parent_exists=True):
        for graph in modules:
            module = self._existing_module(graph, parent, parent_exists)
            self.destinations[id(graph)] = module
            for unit in graph.units:
                yield id(graph), unit
            yield from self._entries(graph.children, module, module is not None)

    def _index_modules(self):
        identities = {}
        slots = {}
        for module in Module.objects.filter(course_id=self.course.pk):
            identities.setdefault(module.source_content_id, module)
            slots[(module.parent_id, module.slug)] = module
        return identities, slots

    def _existing_module(self, graph, parent, parent_exists):
        if graph.content_id:
            existing = self.module_identities.get(_identity(graph.content_id))
            if existing is not None:
                return existing
        if parent_exists:
            parent_id = None
            if parent is not None:
                parent_id = parent.pk
            return self.module_slots.get((parent_id, graph.slug))
        return None

    def _reserve_identities(self, entries):
        incoming = set()
        reserved = set()
        for _destination, graph in entries:
            identity = _identity(graph.content_id)
            if identity is None:
                continue
            if identity in incoming:
                raise CurriculumParseError(
                    f"{graph.source_path}: duplicate unit content_id {identity}"
                )
            incoming.add(identity)
            existing = self.by_identity.get(identity)
            if existing is not None:
                reserved.add(existing.pk)
        return reserved

    def _plan(self, entries, reserved):
        claims = set()
        for destination, graph in entries:
            unit = self.by_identity.get(_identity(graph.content_id))
            module = self.destinations[destination]
            if unit is None:
                unit = self._fallback(module, graph, reserved)
            target = ("new", destination)
            if module is not None:
                target = ("existing", module.pk)
            slot = (target, unit.slug)
            if slot in claims:
                raise CurriculumParseError(
                    f"{graph.source_path}: duplicate unit destination for {unit.slug!r}"
                )
            claims.add(slot)
            self.plans[id(graph)] = (destination, unit)

    def _fallback(self, module, graph, reserved):
        if module is not None:
            existing = self.by_slot.get((module.pk, graph.slug))
            if existing is not None and existing.pk not in reserved:
                return existing
        return Unit(slug=graph.slug)

    def _check_occupants(self):
        retained = {}
        for destination, unit in self.plans.values():
            if unit.pk is not None:
                retained[unit.pk] = self.destinations[destination]
        for destination, unit in self.plans.values():
            module = self.destinations[destination]
            if module is None:
                continue
            occupant = self.by_slot.get((module.pk, unit.slug))
            if occupant is None or occupant.pk == unit.pk:
                continue
            if occupant.pk in retained:
                if retained[occupant.pk] == module:
                    raise CurriculumParseError(
                        f"occupied unit destination {module.slug}/{unit.slug}"
                    )
            elif occupant.source_content_id is None:
                raise CurriculumParseError(f"occupied unit destination {module.slug}/{unit.slug}")
            self.parked[occupant.pk] = occupant

    def park(self):
        # QuerySet.update bypasses rendering and save signals. The containing
        # transaction hides these temporary names and rolls them back on failure.
        for unit in self.parked.values():
            Unit.objects.filter(pk=unit.pk).update(slug=f"_import_{uuid4().hex}")

    def resolve(self, graph):
        _destination, unit = self.plans[id(graph)]
        unit.source_content_id = _identity(graph.content_id)
        return unit

    def delete_stale(self):
        stale = Unit.objects.filter(module_id__in=self.visited_modules)
        stale = stale.exclude(source_content_id__isnull=True).exclude(pk__in=self.seen)
        count = stale.count()
        for unit in stale:
            unit.delete()
        return count
