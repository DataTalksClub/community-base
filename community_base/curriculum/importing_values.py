"""Map authored curriculum values to source-managed model fields."""

import hashlib

from community_base.content_sync.checkout import CheckoutError


def file_checksum(checkout, path: str | None) -> str:
    """Return the SHA-256 of a checkout file, or empty when there is no file."""

    if not path:
        return ""
    try:
        payload = checkout.read_bytes(path)
    except (CheckoutError, OSError):
        return ""
    return hashlib.sha256(payload).hexdigest()


def course_values(graph, commit, checkout) -> dict:
    return {
        "title": graph.title,
        "description": graph.description,
        "cover_image_url": graph.cover_image_url,
        "required_level": graph.required_level,
        "default_unit_required_level": graph.default_unit_required_level,
        "status": graph.status,
        "discussion_url": graph.discussion_url,
        "tags": list(graph.tags),
        "testimonials": list(graph.testimonials),
        "github_repo_url": graph.github_repo_url,
        "docs_url": graph.docs_url,
        "faq_url": graph.faq_url,
        "hashtag": graph.hashtag,
        "visible": graph.visible,
        **_source_values(graph, commit, checkout),
    }


def cohort_values(graph, commit, checkout) -> dict:
    return {
        "title": graph.title,
        "mode": graph.mode,
        "start_date": graph.start_date,
        "end_date": graph.end_date,
        "registration_url": graph.registration_url,
        "hashtag": graph.hashtag,
        "visible": graph.visible,
        **_source_values(graph, commit, checkout),
    }


def module_values(graph, parent, position, commit, checkout) -> dict:
    sort_order = graph.sort_order or position
    return {
        "title": graph.title,
        "sort_order": sort_order,
        "source_sibling_position": graph.source_sibling_position,
        "parent_id": getattr(parent, "pk", None),
        "syllabus_section": graph.syllabus_section,
        "overview": graph.overview,
        "is_bonus": graph.is_bonus,
        "available_after_days": graph.available_after_days,
        **_source_values(graph, commit, checkout),
    }


def unit_values(graph, commit, checkout) -> dict:
    return {
        "title": graph.title,
        "sort_order": graph.sort_order,
        "source_sibling_position": graph.source_sibling_position,
        "kind": graph.kind,
        "session_position": graph.session_position,
        "is_bonus": graph.is_bonus,
        "video_url": graph.video_url,
        "body": graph.body,
        "homework": graph.homework,
        "timestamps": list(graph.timestamps),
        "is_preview": graph.is_preview,
        "required_level": graph.required_level,
        "content_hash": _body_hash(graph),
        **_source_values(graph, commit, checkout),
    }


def _source_values(graph, commit, checkout) -> dict:
    checksum = file_checksum(checkout, graph.source_path)
    return provenance(graph.source_path, commit, checksum)


def provenance(source_path, commit, checksum) -> dict:
    """All-or-nothing provenance, as the table constraint requires."""

    if not (source_path and commit and checksum):
        return {"source_path": None, "source_commit_sha": None, "source_checksum": None}
    return {
        "source_path": source_path,
        "source_commit_sha": commit,
        "source_checksum": checksum,
    }


def _body_hash(graph) -> str:
    payload = graph.body or graph.homework or ""
    if not payload:
        return ""
    return hashlib.md5(payload.encode("utf-8")).hexdigest()
