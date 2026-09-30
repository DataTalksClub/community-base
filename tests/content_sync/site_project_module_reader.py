"""A synthetic host-owned project schema registered through ``--kinds``."""

from community_base.curriculum.project_modules import (
    ProjectModuleReference,
    register_project_module_reader,
)
from community_base.curriculum.source import CurriculumParseError


def read_project_modules(result, collection):
    for document in result.documents:
        if document.collection.index != collection.index or document.part.name != "course":
            continue
        extra = document.data.get("extra") or {}
        for index, row in enumerate(extra.get("project_module_refs", ())):
            if not isinstance(row, dict) or set(row) != {"id", "module_path"}:
                raise CurriculumParseError(
                    f"{document.raw.path}:/extra/project_module_refs/{index}: "
                    "[3.8] host project reference has unknown or missing fields"
                )
            yield ProjectModuleReference(
                project_id=row["id"],
                source_path=document.raw.path,
                module_path=row["module_path"],
                pointer=f"/extra/project_module_refs/{index}/module_path",
            )


register_project_module_reader(read_project_modules)
