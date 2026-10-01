"""Diagnostic attribution and redaction policy for package page imports."""

from pathlib import PurePosixPath

from community_base.content_sync.documents import MANIFEST_NAME, Diagnostic
from community_base.kernel import conf
from community_base.kernel.redaction import mask_sensitive_spans, redact
from community_base.knowledge_base.page_adaptation import PageError

IMAGE_SUFFIXES = frozenset({".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"})


def family_diagnostics(view, kind: str, diagnostics) -> tuple[Diagnostic, ...]:
    """Select global, owned, or ambiguous diagnostics for one page family."""

    selected = []
    for diagnostic in diagnostics:
        if diagnostic.path == MANIFEST_NAME:
            selected.append(diagnostic)
            continue
        matches = _matching_collections(view, diagnostic.path)
        if len(matches) != 1 or matches[0].kind.name == kind:
            selected.append(diagnostic)
    return tuple(selected)


def is_missing_image(diagnostic: Diagnostic, source_paths: set[str]) -> bool:
    """Return whether package policy admits one cleanup-safe missing image."""

    if diagnostic.path not in source_paths:
        return False
    if diagnostic.rule != "3.6" or not diagnostic.message.endswith(" does not exist"):
        return False
    prefix = "asset "
    if not diagnostic.message.startswith(prefix):
        return False
    path = diagnostic.message[len(prefix) : -len(" does not exist")]
    return PurePosixPath(path).suffix.lower() in IMAGE_SUFFIXES


def diagnostic_error(diagnostic: Diagnostic) -> PageError:
    return PageError(
        file=diagnostic.path,
        error=diagnostic.render(),
        step="content_format",
        kind="content_format",
    )


def redact_page_error(error: PageError, source) -> PageError:
    """Bound one adapter error and remove configured secrets and source canaries."""

    canaries = _canaries(source)
    values = redact(error.record, canaries=canaries)
    if not isinstance(values, dict):
        raise TypeError("Redacted page error must remain a mapping")
    return PageError(
        file=str(values["file"]),
        error=mask_sensitive_spans(error.error, canaries=canaries)[:1000],
        step=str(values["step"]),
        kind=str(values["kind"]),
        filesystem_boundary=values["filesystem_boundary"] is True,
        retryable=values["retryable"] is True,
    )


def _matching_collections(view, path: str):
    matches = []
    for collection in view.read.manifest.collections:
        if not collection.path:
            matches.append(collection)
        elif path == collection.path or path.startswith(f"{collection.path}/"):
            matches.append(collection)
    return matches


def _canaries(source) -> tuple[str, ...]:
    canaries = []
    secret = str(getattr(source, "webhook_secret", "") or "")
    if secret:
        canaries.append(secret)
    private_key = str(conf.get("CONTENT_SYNC_GITHUB_PRIVATE_KEY") or "")
    if private_key:
        canaries.append(private_key)
    return tuple(canaries)
