"""Structured project evaluation criteria authored as YAML.

Supports both standalone reusable criteria sets (synced via git/YAML) and
per-project required criteria references.
"""

import re
from collections.abc import Iterable, Mapping

CRITERION_TYPES = ("scale", "checklist")
CRITERIA_REF_PREFIX = "review_criteria:"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CriteriaError(ValueError):
    """Invalid authored criteria; sync layers convert it to their sync error."""


class MissingProjectCriteriaError(CriteriaError):
    """Raised when a project has no review criteria set referenced or assigned."""


def parse_criteria(raw, where: str) -> list[dict]:
    """Validate and normalize a criteria list; raise CriteriaError on bad input."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CriteriaError(f"{where}: criteria must be a list")
    seen: set[str] = set()
    return [_parse_criterion(item, where, seen) for item in raw]


def _parse_criterion(item, where: str, seen: set[str]) -> dict:
    if not isinstance(item, dict):
        raise CriteriaError(f"{where}: each criterion must be a mapping")
    cid = item.get("id")
    if not isinstance(cid, str) or not _ID_RE.match(cid):
        raise CriteriaError(f"{where}: criterion id {cid!r} must be a lowercase slug")
    if cid in seen:
        raise CriteriaError(f"{where}: duplicate criterion id {cid!r}")
    seen.add(cid)
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CriteriaError(f"{where}: criterion {cid!r} requires a title")
    kind = item.get("type", "scale")
    if kind not in CRITERION_TYPES:
        raise CriteriaError(
            f"{where}: criterion {cid!r} type must be one of {', '.join(CRITERION_TYPES)}"
        )
    options = item.get("options")
    if not isinstance(options, list) or not options:
        raise CriteriaError(f"{where}: criterion {cid!r} requires options")
    return {
        "id": cid,
        "title": title.strip(),
        "description": str(item.get("description") or "").strip(),
        "type": kind,
        "options": [_parse_option(opt, cid, where) for opt in options],
    }


def _parse_option(opt, cid: str, where: str) -> dict:
    if not isinstance(opt, dict):
        raise CriteriaError(f"{where}: criterion {cid!r} options must be mappings")
    points = opt.get("points")
    text = opt.get("text")
    if not isinstance(points, int) or isinstance(points, bool) or points < 0:
        raise CriteriaError(
            f"{where}: criterion {cid!r} option points must be a non-negative integer"
        )
    if not isinstance(text, str) or not text.strip():
        raise CriteriaError(f"{where}: criterion {cid!r} option requires text")
    return {"points": points, "text": text.strip()}


def _stored_option(option) -> dict | None:
    if not isinstance(option, dict):
        return None
    points = option.get("points")
    if isinstance(points, bool) or not isinstance(points, int):
        points = 0
    return {**option, "points": points, "text": str(option.get("text") or "")}


def _stored_criterion(criterion) -> dict | None:
    if not isinstance(criterion, dict):
        return None
    cid = str(criterion.get("id") or "")
    kind = criterion.get("type")
    options = criterion.get("options")
    options = options if isinstance(options, list) else []
    return {
        **criterion,
        "id": cid,
        "title": str(criterion.get("title") or cid),
        "description": str(criterion.get("description") or ""),
        "type": kind if kind in CRITERION_TYPES else "scale",
        "options": [opt for opt in map(_stored_option, options) if opt is not None],
    }


def normalize_stored_criteria(criteria) -> list[dict]:
    """Fill the keys stored criteria may lack (admin or raw JSON writes) so they render.

    Output of ``parse_criteria`` passes through unchanged; non-mapping items are dropped.
    """
    items = criteria if isinstance(criteria, list | tuple) else []
    return [c for c in map(_stored_criterion, items) if c is not None]


def max_points(criterion: dict) -> int:
    points = [opt["points"] for opt in criterion["options"]]
    if criterion["type"] == "checklist":
        return sum(points)
    return max(points, default=0)


def split_criteria(criteria: list[dict]) -> tuple[list[dict], list[dict]]:
    """(core scale criteria, bonus checklists) for display."""
    core = [c for c in criteria if c["type"] == "scale"]
    bonus = [c for c in criteria if c["type"] == "checklist"]
    return core, bonus


LIST_INTROS = {"scale": "Scoring:", "checklist": "Bonus points (checklist):"}


def points_label(points: int) -> str:
    """'0 points', '1 point', '2 points'."""
    if points == 1:
        return "1 point"
    return f"{points} points"


def _summary_option(option: dict) -> dict:
    return {**option, "label": f"{option['text']}: {points_label(option['points'])}"}


def _summary_row(criterion: dict) -> dict:
    """One criterion in authored order with its list intro and option lines."""
    options = [_summary_option(opt) for opt in criterion["options"]]
    return {
        **criterion,
        "max_points": max_points(criterion),
        "list_intro": LIST_INTROS[criterion["type"]],
        "options": options,
    }


def criteria_summary(criteria: list[dict]) -> dict:
    """Template-ready rows (authored order) plus core and bonus totals."""
    rows = [_summary_row(c) for c in normalize_stored_criteria(criteria)]
    core, bonus = split_criteria(rows)
    core_max = sum(r["max_points"] for r in core)
    bonus_max = sum(r["max_points"] for r in bonus)
    return {
        "criteria": rows,
        "core_max": core_max,
        "bonus_max": bonus_max,
        "totals_label": totals_label(core_max, bonus_max),
    }


def totals_label(core_max: int, bonus_max: int) -> str:
    """'up to 18 points, plus up to 17 bonus points' (no bonus part when 0)."""
    label = f"up to {core_max} points"
    if bonus_max:
        label += f", plus up to {bonus_max} bonus points"
    return label


def score_review(criteria: list[dict], data) -> tuple[dict, int, list[str]]:
    """Parse posted per-criterion choices."""
    scores: dict = {}
    total = 0
    missing: list[str] = []
    for criterion in criteria:
        key = f"criterion-{criterion['id']}"
        options = criterion["options"]
        if criterion["type"] == "checklist":
            raw_list = data.getlist(key) if hasattr(data, "getlist") else (data.get(key) or [])
            picked = sorted(
                {int(v) for v in raw_list if str(v).isdigit() and int(v) < len(options)}
            )
            scores[criterion["id"]] = picked
            total += sum(options[i]["points"] for i in picked)
            continue
        raw = str(data.get(key, ""))
        if not raw.isdigit() or int(raw) >= len(options):
            missing.append(criterion["title"])
            continue
        scores[criterion["id"]] = int(raw)
        total += options[int(raw)]["points"]
    return scores, total, missing


def scores_complete(criteria: list[dict], scores) -> bool:
    """True when every scale criterion has a valid stored answer."""
    scores = scores if isinstance(scores, dict) else {}
    for criterion in criteria:
        if criterion["type"] == "checklist":
            continue
        value = scores.get(criterion["id"])
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        if not 0 <= value < len(criterion["options"]):
            return False
    return True


def is_review_complete(review) -> bool:
    """Whether a review is submitted/complete across package and site models."""
    if hasattr(review, "is_complete"):
        return bool(review.is_complete)
    return getattr(review, "state", None) == "SU"


def settle_completion(reviews, criteria: list[dict]) -> list:
    """Defensive: un-complete, in memory only, reviews missing a required answer."""
    reviews = list(reviews)
    if criteria:
        for review in reviews:
            if is_review_complete(review) and not scores_complete(criteria, review.criteria_scores):
                if hasattr(review, "is_complete"):
                    review.is_complete = False
                elif hasattr(review, "state"):
                    review.state = "TR"
    return reviews


def require_criteria(raw, where: str) -> list[dict]:
    """Validate a non-empty criteria list; raise CriteriaError when empty or missing."""
    criteria = parse_criteria(raw, where)
    if not criteria:
        raise CriteriaError(f"{where}: criteria set must define at least one criterion")
    return criteria


def parse_criteria_set(raw, where: str, *, default_slug: str = "") -> dict:
    """Validate and normalize one standalone reusable review criteria set."""
    if not isinstance(raw, Mapping):
        raise CriteriaError(f"{where}: criteria set must be a mapping")
    slug = raw.get("slug") or default_slug
    if not isinstance(slug, str) or not _ID_RE.match(slug):
        raise CriteriaError(f"{where}: criteria set slug {slug!r} must be a lowercase slug")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CriteriaError(f"{where}: criteria set {slug!r} requires a title")
    criteria = require_criteria(raw.get("criteria"), where)
    parsed = {
        "slug": slug,
        "title": title.strip(),
        "description": str(raw.get("description") or "").strip(),
        "criteria": criteria,
    }
    if "content_id" in raw and raw["content_id"] is not None:
        parsed["content_id"] = str(raw["content_id"]).strip()
    return parsed


def normalize_criteria_ref(ref: str) -> str:
    """Normalize a project's criteria reference (strips ``review_criteria:`` prefix)."""
    cleaned = ref.strip()
    if cleaned.startswith(CRITERIA_REF_PREFIX):
        return cleaned[len(CRITERIA_REF_PREFIX) :]
    return cleaned


def resolve_project_criteria(
    ref: str | None,
    criteria_sets: Mapping[str, list[dict] | Mapping],
    *,
    where: str,
) -> list[dict]:
    """Resolve a project's required criteria set reference against available criteria sets."""
    if not isinstance(ref, str) or not ref.strip():
        raise MissingProjectCriteriaError(f"{where}: project must reference a review criteria set")
    key = normalize_criteria_ref(ref)
    if key not in criteria_sets:
        raise MissingProjectCriteriaError(f"{where}: unknown review criteria set {ref!r}")
    entry = criteria_sets[key]
    criteria = entry["criteria"] if isinstance(entry, Mapping) and "criteria" in entry else entry
    if not criteria:
        raise CriteriaError(f"{where}: review criteria set {key!r} has no criteria")
    return list(criteria)


def _extract_project_ref(project) -> tuple[str, str | None]:
    if isinstance(project, Mapping):
        name = str(project.get("slug") or project.get("id") or project.get("title") or "<project>")
        ref = (
            project.get("criteria") or project.get("review_criteria") or project.get("criteria_set")
        )
        return name, ref
    name = str(
        getattr(project, "slug", None)
        or getattr(project, "id", None)
        or getattr(project, "title", None)
        or "<project>"
    )
    ref = (
        getattr(project, "criteria", None)
        or getattr(project, "review_criteria", None)
        or getattr(project, "criteria_set", None)
    )
    return name, ref


def validate_project_criteria_references(
    projects: Iterable,
    criteria_sets: Mapping[str, list[dict] | Mapping],
    *,
    where: str = "projects",
) -> dict[str, list[dict]]:
    """Ensure every project references an existing criteria set (shared or distinct)."""
    resolved: dict[str, list[dict]] = {}
    for project in projects:
        name, ref = _extract_project_ref(project)
        resolved[name] = resolve_project_criteria(ref, criteria_sets, where=f"{where}:{name}")
    return resolved


def project_evaluation_criteria(project) -> list[dict]:
    """Return a project's structured criteria list from its assigned set or inline attribute."""
    if project is None:
        return []
    inline = getattr(project, "evaluation_criteria", None)
    if inline:
        return list(inline)
    try:
        assignment = project.criteria_set_assignment
    except Exception:
        assignment = None
    if assignment is not None:
        criteria_set = getattr(assignment, "criteria_set", None)
        if criteria_set is not None and getattr(criteria_set, "criteria", None):
            return list(criteria_set.criteria)
    return []


def require_project_criteria(project) -> list[dict]:
    """Return a project's structured criteria list, or raise MissingProjectCriteriaError."""
    criteria = project_evaluation_criteria(project)
    if not criteria:
        raise MissingProjectCriteriaError(
            f"Project {project!r} has no review criteria set assigned."
        )
    return criteria


def get_project_criteria_set(project):
    """Return the ReviewCriteriaSet assigned to ``project``, or None."""
    from community_base.coursework.models import ProjectCriteriaSetAssignment

    if project is None or not getattr(project, "pk", None):
        return None
    assignment = (
        ProjectCriteriaSetAssignment.objects.filter(project_id=project.pk)
        .select_related("criteria_set")
        .first()
    )
    return assignment.criteria_set if assignment is not None else None


def assign_project_criteria_set(project, criteria_set_or_ref):
    """Bind ``project`` to a standalone ``ReviewCriteriaSet`` (by instance or slug).

    Raises MissingProjectCriteriaError when the reference is missing/blank or
    no matching ReviewCriteriaSet exists.
    """
    from community_base.coursework.models import (
        ProjectCriteriaSetAssignment,
        ReviewCriteriaSet,
    )

    if isinstance(criteria_set_or_ref, ReviewCriteriaSet):
        criteria_set = criteria_set_or_ref
    elif isinstance(criteria_set_or_ref, str) and criteria_set_or_ref.strip():
        slug = normalize_criteria_ref(criteria_set_or_ref)
        criteria_set = ReviewCriteriaSet.objects.filter(slug=slug).first()
        if criteria_set is None:
            raise MissingProjectCriteriaError(
                f"Project {project!r}: unknown review criteria set {criteria_set_or_ref!r}."
            )
    else:
        raise MissingProjectCriteriaError(
            f"Project {project!r}: project must reference a review criteria set."
        )
    assignment, _created = ProjectCriteriaSetAssignment.objects.update_or_create(
        project=project,
        defaults={"criteria_set": criteria_set},
    )
    if hasattr(project, "_state"):
        project._state.fields_cache["criteria_set_assignment"] = assignment
    return assignment
