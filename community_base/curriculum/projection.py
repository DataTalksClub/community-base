"""One batched curriculum tree and cohort-scoped reading projection."""

from dataclasses import dataclass, field

from django.http import Http404
from django.urls import reverse

from community_base.curriculum.models import CohortModule, Module, Unit


def curriculum_url(course, cohort, item, path):
    """Preserve flat routes; nested destinations include every ancestor slug."""
    if isinstance(item, Module) and item.parent_id is None:
        return reverse("curriculum_module_overview", args=[course.slug, cohort.slug, item.slug])
    if isinstance(item, Unit) and item.module.parent_id is None:
        return reverse(
            "curriculum_unit_detail", args=[course.slug, cohort.slug, item.module.slug, item.slug]
        )
    return reverse("curriculum_nested_detail", args=[course.slug, cohort.slug, "/".join(path)])


def ordered_siblings(units, children):
    siblings = [*units, *children]
    if not units or not children:
        return siblings
    positioned, unpositioned = [], []
    for item in siblings:
        if item.source_sibling_position is None:
            unpositioned.append(item)
        else:
            positioned.append(item)
    positioned.sort(key=lambda item: item.source_sibling_position)
    return positioned + unpositioned


@dataclass
class CurriculumNode:
    item: Module | Unit
    path: tuple[str, ...]
    url: str
    ancestors: tuple = ()
    children: list = field(default_factory=list)

    @property
    def is_module(self):
        return isinstance(self.item, Module)

    def get_absolute_url(self):
        return self.url


class CourseTree:
    """Load each module/unit once; wire parent relations without depth-dependent queries."""

    def __init__(self, course):
        self.course = course
        self.modules = list(course.modules.prefetch_related("units").order_by("sort_order", "pk"))
        self.by_id = {module.pk: module for module in self.modules}
        self.children = {}
        self.roots = []
        self.placements = None
        for module in self.modules:
            module.course = course
            self.children.setdefault(module.parent_id, []).append(module)
            if module.parent_id is None:
                self.roots.append(module)
            else:
                module.parent = self.by_id[module.parent_id]
            for unit in module.units.all():
                unit.module = module
        for module in self.modules:
            cached = Module.objects.none()
            cached._result_cache = self.children.get(module.pk, [])
            module._prefetched_objects_cache["children"] = cached

    def modules_for(self, cohort=None):
        if cohort is None:
            return self.roots
        if cohort.course_id != self.course.pk:
            raise ValueError("Cohort must belong to this course")
        if self.placements is None:
            self.placements = {}
            rows = CohortModule.objects.filter(cohort__course=self.course).order_by(
                "cohort_id", "sort_order", "pk"
            )
            for row in rows:
                self.placements.setdefault(row.cohort_id, []).append(self.by_id[row.module_id])
        return self.placements.get(cohort.pk) or self.roots

    def siblings(self, module):
        return ordered_siblings(module.units.all(), self.children.get(module.pk, []))

    def ordered_units(self, cohort=None):
        units = []
        for item, _ancestors in self.walk(self.modules_for(cohort)):
            if isinstance(item, Unit):
                units.append(item)
        return units

    def walk(self, siblings, ancestors=()):
        for item in siblings:
            yield item, ancestors
            if isinstance(item, Module):
                yield from self.walk(self.siblings(item), (*ancestors, item))

    def project(self, cohort, url_builder=curriculum_url, *, use_placements=True):
        if cohort.course_id != self.course.pk:
            raise ValueError("Cohort must belong to this course")
        modules = self.roots
        if use_placements:
            modules = self.modules_for(cohort)
        return CurriculumProjection(self, cohort, url_builder, modules)


def get_syllabus(course, tree=None):
    if tree is None:
        tree = CourseTree(course)
    cohorts = list(course.cohorts.order_by("start_date", "pk"))
    for cohort in cohorts:
        cohort.syllabus_modules = tree.modules_for(cohort)
    return cohorts


class CurriculumProjection:
    """Prepared URLs, ancestors and reading order for one cohort and URL adapter."""

    def __init__(self, tree, cohort, url_builder, modules):
        self.tree = tree
        self.cohort = cohort
        self.url_builder = url_builder
        self.by_path = {}
        self.units = []
        self.entries = []
        self.roots = []
        self._load(modules)

    def _load(self, modules):
        module_nodes = {}
        for item, parents in self.tree.walk(modules):
            ancestors = tuple(module_nodes[parent.pk] for parent in parents)
            path = tuple(parent.slug for parent in parents) + (item.slug,)
            url = self.url_builder(self.tree.course, self.cohort, item, path)
            node = CurriculumNode(item, path, url, ancestors)
            if ancestors:
                ancestors[-1].children.append(node)
            else:
                self.roots.append(node)
            self.by_path[path] = node
            self.entries.append(node)
            if node.is_module:
                module_nodes[item.pk] = node
            else:
                self.units.append(node)

    def resolve(self, path):
        node = self.by_path.get(tuple(path.split("/")))
        if node is None:
            raise Http404("Curriculum destination not found")
        return node

    def neighbors(self, unit):
        previous = None
        for index, node in enumerate(self.units):
            if node.item.pk == unit.pk:
                following = None
                if index + 1 < len(self.units):
                    following = self.units[index + 1]
                return previous, following
            previous = node
        return None, None

    def first_unfinished(self, completed):
        for node in self.units:
            if node.item.pk not in completed:
                return node
        return None
