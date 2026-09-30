"""Cohort conversion refusals before the manifest or homework is rewritten."""

from collections.abc import Mapping
from typing import Any


def cohort_refusal(values: Mapping[str, Any], identifier: str) -> str | None:
    """Name unsupported placement or contradictory cohort metadata."""

    if values.get("flow"):
        return (
            "nonempty flow needs a host-owned mapping preserving ordered module/project "
            "placement; the cohort scope is left unchanged"
        )
    written = values.get("identifier")
    if written is not None and str(written) != identifier:
        return f"identifier is {written!r} and the directory is {identifier!r}"
    curriculum = values.get("curriculum")
    archived = values.get("archive") is not None
    if curriculum is not None and (curriculum == "github_archive") != archived:
        archive_state = "not set"
        if archived:
            archive_state = "set"
        return f"curriculum is {curriculum!r} and archive is {archive_state}"
    if archived and not isinstance(values["archive"], Mapping):
        return "archive is a mapping with an optional notice_path (D38)"
    return None
