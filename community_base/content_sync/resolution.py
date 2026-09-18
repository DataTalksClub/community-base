"""The resolving half of the document toolkit: assets and cross-references.

This module is `FORMAT.md` sections 3.6 and 3.7. It takes what
:mod:`community_base.content_sync.documents` read, resolves every relative
asset and every cross-reference against the repository, uploads the assets a
document actually references, rewrites both in the rendered HTML and in the
stored asset keys, and returns the resolved reference list a record carries.

There is one implementation of these rules, as there is one implementation of
the reading half. `check.py` is a consumer: it calls :func:`resolve_repository`
with no media store and reports the diagnostics that come back, so the rule the
validator enforces is the rule the sync applies. A parser is the other consumer
and reads :class:`ResolvedDocument` values.

Rendering is not owned here either. `rendering.py` is the one renderer and the
one sanitizer; this module uses its seam, :func:`~.rendering.render_html`, which
is the dialect and the heading ids without the sanitizer, rewrites the HTML that
comes back and hands it to :func:`~.rendering.sanitize_rendered_html`. The order
matters: a relative `img src` does not survive the allowlist, so a rewrite after
the sanitizer would rewrite an attribute that is already gone.

Errors are bounded and named, as in the reading half: nothing raises on a
malformed repository, every violation is one :class:`~.documents.Diagnostic`
carrying the referencing file, a pointer and the rule number, and resolution
continues.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from community_base.content_sync.documents import (
    Collection,
    Diagnostic,
    ParsedDocument,
    ReadResult,
    Repository,
    locate,
)
from community_base.content_sync.kinds import (
    ASSET_SUFFIXES,
    MAX_ASSET_BYTES,
    effective_keys,
    is_registered,
    kind_order,
)
from community_base.content_sync.kinds.base import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    TYPED_REFERENCE_PATTERN,
    check_asset_reference,
)
from community_base.content_sync.media import asset_payload_defect
from community_base.content_sync.rendering import (
    plain_text,
    render_html,
    sanitize_rendered_html,
)

__all__ = [
    "DARK_SUFFIX",
    "THEME_FIGURE_CLASS",
    "ResolutionResult",
    "ResolvedAsset",
    "ResolvedDocument",
    "ResolvedReference",
    "hosting_url_for",
    "order_sources",
    "resolve_repository",
]

#: The sibling that makes a referenced image a theme pair (section 3.6).
DARK_SUFFIX = ".dark"

#: The class hook a site styles; the variant also rides on `data-theme-figure`.
THEME_FIGURE_CLASS = "cb-theme-figure"

#: Schemes a destination may carry and still be left alone (section 3.7).
EXTERNAL_SCHEMES = ("http", "https", "mailto", "tel", "ftp")

_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_IMAGE = re.compile(r"<img\b[^>]*?/?>", re.IGNORECASE)
_HREF = re.compile(r"\bhref\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
_SRC = re.compile(r"\bsrc\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
_CLASS = re.compile(r"\bclass\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
_TAG_END = re.compile(r"\s*/?>$")


# --- what resolution yields ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """One referenced file, checked once and uploaded once (section 3.6)."""

    path: str
    url: str
    dark_path: str = ""
    dark_url: str = ""

    @property
    def is_paired(self) -> bool:
        """Whether `theme_pairs` found a `name.dark.ext` sibling."""

        return bool(self.dark_path)


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    """One resolved cross-reference, in the four keys a record stores."""

    kind: str
    target: str
    label: str
    href: str

    def record(self) -> dict[str, str]:
        return {"kind": self.kind, "target": self.target, "label": self.label, "href": self.href}


@dataclass(frozen=True, slots=True)
class ResolvedDocument:
    """One item after its assets and references resolved."""

    document: ParsedDocument
    html: str = ""
    headings: tuple[dict[str, object], ...] = ()
    text: str = ""
    assets: tuple[ResolvedAsset, ...] = ()
    references: tuple[ResolvedReference, ...] = ()
    values: Mapping[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.document.kind

    @property
    def path(self) -> str:
        return self.document.path

    @property
    def source_path(self) -> str:
        return self.document.source_path

    def reference_records(self) -> list[dict[str, str]]:
        """The stored reference list: `{kind, target, label, href}` each."""

        return [reference.record() for reference in self.references]


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """What one repository resolved to: documents, assets and diagnostics."""

    documents: tuple[ResolvedDocument, ...] = ()
    assets: tuple[ResolvedAsset, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == SEVERITY_ERROR)

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == SEVERITY_WARNING)

    @property
    def ok(self) -> bool:
        """True when no rule of the resolving half rejected this repository."""

        return not self.errors

    def by_path(self) -> dict[str, ResolvedDocument]:
        return {item.source_path: item for item in self.documents}


def resolve_repository(
    result: ReadResult,
    *,
    media: Any = None,
    source: Any = None,
    routes: Callable[[str, str], str | None] | None = None,
    hosting_url: str = "",
) -> ResolutionResult:
    """Resolve the assets and references of one already-read repository.

    `result` comes from :func:`~.documents.read_repository`. `media` is a store
    from :mod:`community_base.content_sync.media`; without one nothing is
    uploaded and a reference is rewritten to the repository path, which is what
    the validator wants. `source` is the row a store keys its uploads by.

    `routes` is the site's route resolver (section 3.7): it answers
    `(kind, target)` with a route or with None. A kind this repository declares
    is resolved against this repository first, and `routes` only says where the
    target lives; a kind another source owns is resolved by `routes` alone, and
    without one such a reference is left for the sync that has the other source
    rather than reported.

    `hosting_url` is where this repository's own files are served, the base a
    repository-file destination is rewritten against (section 3.7, decision
    D39). Without one such a destination is left as written, which is what the
    validator wants: it has no source and therefore no hosting URL.
    """

    if result.repository is None:
        return ResolutionResult()
    return _Resolution(
        result, media=media, source=source, routes=routes, hosting_url=hosting_url
    ).run()


def hosting_url_for(source: Any, commit_sha: str = "") -> str:
    """Where a source's own files are served, for the fourth destination form.

    Section 3.7 resolves a repository-file destination against the repository's
    hosting URL. A `ContentSource` names a GitHub repository, so the URL is that
    repository at the synced commit, and at its default branch when the commit
    is not known. A source without a repository name has no hosting URL and the
    destination is left as written.
    """

    repo_name = str(getattr(source, "repo_name", "") or "").strip("/")
    if not repo_name:
        return ""
    reference = commit_sha.strip() or "HEAD"
    return f"https://github.com/{repo_name}/blob/{reference}"


def order_sources(
    sources: Iterable[Any],
    *,
    kinds: Callable[[Any], Iterable[str]] | None = None,
) -> tuple[Any, ...]:
    """Sources in the order the declared kind dependencies imply (section 3.7).

    A reference resolves against rows already synced, so a source whose kinds
    another source depends on is synced first. The order comes from
    :func:`~.kinds.kind_order` and from nothing hand-written: a source ranks by
    the earliest of its kinds in that order, and sources of equal rank keep the
    order they were given. `kinds` names the kinds of one source; the default
    reads the collections of a :class:`~.documents.ReadResult`.

    A cycle in the declared graph raises `KindDependencyError` naming its
    members, as `kind_order` does.
    """

    listed = list(sources)
    read_kinds = kinds or _result_kinds
    names: list[str] = []
    for item in listed:
        names.extend(read_kinds(item))
    rank = {name: index for index, name in enumerate(kind_order(names))}
    return tuple(
        sorted(
            listed,
            key=lambda item: min(
                (rank.get(name, len(rank)) for name in read_kinds(item)), default=len(rank)
            ),
        )
    )


def _result_kinds(result: Any) -> tuple[str, ...]:
    return tuple(collection.kind.name for collection in result.collections)


# --- one repository -----------------------------------------------------------


class _Resolution:
    """One resolution pass, holding what every document needs to resolve."""

    def __init__(
        self,
        result: ReadResult,
        *,
        media: Any,
        source: Any,
        routes: Callable[[str, str], str | None] | None,
        hosting_url: str = "",
    ) -> None:
        self.read = result
        self.hosting_url = hosting_url.rstrip("/")
        self.repository: Repository = result.repository
        self.manifest = result.manifest
        self.media = media
        self.source = source
        self.routes = routes
        self.severity = SEVERITY_ERROR if self.manifest.strict_references else SEVERITY_WARNING
        self.diagnostics: list[Diagnostic] = []
        self.by_document = result.by_path()
        self.by_collection: dict[int, dict[str, ParsedDocument]] = {}
        for item in result.documents:
            self.by_collection.setdefault(item.collection.index, {})[item.path] = item
        self.declared: dict[str, Collection] = {
            collection.kind.name: collection for collection in result.manifest.collections
        }
        self.assets: dict[str, ResolvedAsset] = {}
        self.defects: dict[str, str] = {}
        self.rendered: dict[str, tuple[str, tuple[dict[str, object], ...]]] = {}

    # -- the pass ------------------------------------------------------------

    def run(self) -> ResolutionResult:
        for item in self.read.documents:
            if item.is_document:
                self.rendered[item.raw.path] = render_html(item.body, item.title)
        documents = tuple(self._resolve(item) for item in self.read.documents)
        return ResolutionResult(
            documents=documents,
            assets=tuple(self.assets[path] for path in sorted(self.assets)),
            diagnostics=tuple(sorted(self.diagnostics, key=lambda item: item.sort_key)),
        )

    def _resolve(self, item: ParsedDocument) -> ResolvedDocument:
        assets: list[ResolvedAsset] = []
        references: list[ResolvedReference] = []
        values = dict(item.values)
        for name, asset in self._front_matter_assets(item):
            assets.append(asset)
            values[name] = asset.url
        references.extend(self._front_matter_references(item))
        html, headings, text = "", (), ""
        if item.is_document:
            rendered, headings = self.rendered[item.raw.path]
            rendered = self._rewrite_images(item, rendered, assets)
            rendered = self._rewrite_links(item, rendered, assets, references)
            html = sanitize_rendered_html(rendered)
            text = plain_text(html)
        return ResolvedDocument(
            document=item,
            html=html,
            headings=headings,
            text=text,
            assets=tuple({asset.path: asset for asset in assets}.values()),
            references=tuple(references),
            values=values,
        )

    # -- front matter, sections 3.6 and 3.7 ----------------------------------

    def _front_matter_assets(self, item: ParsedDocument) -> list[tuple[str, ResolvedAsset]]:
        found: list[tuple[str, ResolvedAsset]] = []
        keys = effective_keys(item.part)
        for name in item.collection.kind.asset_key_names(item.part):
            value = item.data.get(name)
            if not isinstance(value, str) or not value.strip():
                continue
            pointer = f"/{name}"
            problems = check_asset_reference(value, pointer)
            if problems:
                spec = keys.get(name)
                if spec is None or spec.type != "asset":
                    # A key the kind named an asset without declaring the type
                    # has had no shape check yet; one the registry typed
                    # `asset` already reported these and must not report twice.
                    for problem in problems:
                        self.diagnostics.append(locate(item.raw.path, problem))
                continue
            if value.strip().startswith("https://"):
                continue
            asset = self._asset(item, value.strip(), pointer, None)
            if asset is not None:
                found.append((name, asset))
        return found

    def _front_matter_references(self, item: ParsedDocument) -> list[ResolvedReference]:
        found: list[ResolvedReference] = []
        for pointer, value in _reference_key_values(item):
            reference = self._typed(item, value, pointer, "", None)
            if reference is not None:
                found.append(reference)
        return found

    # -- the body, sections 3.6 and 3.7 --------------------------------------

    def _rewrite_images(
        self, item: ParsedDocument, rendered: str, assets: list[ResolvedAsset]
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            tag = match.group(0)
            found = _SRC.search(tag)
            if found is None:
                return tag
            destination = html_lib.unescape(found.group(2)).strip()
            if not destination or destination.startswith("#"):
                return tag
            line = self._line(item, destination)
            if _is_external(destination):
                for problem in check_asset_reference(destination, "/body", line):
                    self.diagnostics.append(locate(item.raw.path, problem))
                return tag
            asset = self._asset(item, destination, "/body", line)
            if asset is None:
                return tag
            assets.append(asset)
            if asset.is_paired:
                return _theme_pair(tag, asset)
            return _with_source(tag, asset.url)

        return _IMAGE.sub(replace, rendered)

    def _rewrite_links(
        self,
        item: ParsedDocument,
        rendered: str,
        assets: list[ResolvedAsset],
        references: list[ResolvedReference],
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            tag, label_html = match.group(0), match.group(2)
            found = _HREF.search(match.group(1))
            if found is None:
                return tag
            destination = html_lib.unescape(found.group(2)).strip()
            if not destination or destination.startswith("#") or _is_external(destination):
                return tag
            label = plain_text(label_html)
            line = self._line(item, destination)
            if TYPED_REFERENCE_PATTERN.match(destination):
                reference = self._typed(item, destination, "/body", label, line)
            elif _names_an_asset(destination):
                # A link to a file of an allowed asset type is an asset, not a
                # document: this is how a PDF is uploaded and rewritten. An
                # asset is decided before the repository-file form, so a PDF of
                # this repository stays an upload.
                asset = self._asset(item, destination, "/body", line)
                if asset is None:
                    return tag
                assets.append(asset)
                return _with_href(tag, asset.url)
            elif self._is_repository_file(item, destination):
                # Section 3.7, the fourth destination form: a file or directory
                # of this repository that is not content. The validator has no
                # hosting URL and leaves the destination as written.
                href = self._repository_href(item, destination)
                return tag if href is None else _with_href(tag, href)
            else:
                reference = self._relative(item, destination, label, line)
            if reference is None:
                return tag if self.severity == SEVERITY_ERROR else label_html
            references.append(reference)
            return _with_href(tag, reference.href)

        return _ANCHOR.sub(replace, rendered)

    # -- one reference, section 3.7 ------------------------------------------

    def _typed(
        self,
        item: ParsedDocument,
        destination: str,
        pointer: str,
        label: str,
        line: int | None,
    ) -> ResolvedReference | None:
        match = TYPED_REFERENCE_PATTERN.match(destination)
        if match is None:
            self._report(item, pointer, "3.7", f"must be kind:target, found {destination!r}", line)
            return None
        name = match.group(1)
        target, _, fragment = match.group(2).partition("#")
        if not is_registered(name):
            self._report(item, pointer, "3.7", f"unknown kind in a typed reference: {name}", line)
            return None
        collection = self.declared.get(name)
        if collection is not None:
            if target not in self.by_collection.get(collection.index, {}):
                self._report(
                    item,
                    pointer,
                    "3.7",
                    f"unresolved reference: no {name} with the path {target!r} in this repository",
                    line,
                    severity=self.severity,
                )
                return None
            href = self._route(collection.kind.name, target, collection)
        else:
            if self.routes is None:
                # Another source owns this kind. It resolves at sync, against
                # the rows that source already wrote; a validator run over one
                # repository cannot say more than that.
                return None
            href = self.routes(name, target)
            if not href:
                self._report(
                    item,
                    pointer,
                    "3.7",
                    f"unresolved reference: no {name} with the path {target!r}",
                    line,
                    severity=self.severity,
                )
                return None
        return ResolvedReference(
            kind=name, target=target, label=label, href=_with_fragment(href, fragment)
        )

    def _relative(
        self, item: ParsedDocument, destination: str, label: str, line: int | None
    ) -> ResolvedReference | None:
        if destination.startswith("/"):
            self._report(
                item,
                "/body",
                "3.7",
                f"a link is relative, typed or external; found the absolute path {destination!r}",
                line,
            )
            return None
        target, _, fragment = destination.partition("#")
        if not target:
            return None
        resolved = _resolve_relative(item.raw.path, target)
        if resolved is None:
            self._report(
                item, "/body", "3.6", f"reference leaves the repository: {destination}", line
            )
            return None
        target_item = self.by_document.get(resolved)
        if target_item is None:
            self._report(
                item,
                "/body",
                "3.7",
                f"relative link resolves to no document of this collection: {destination}",
                line,
                severity=self.severity,
            )
            return None
        if target_item.collection.index != item.collection.index:
            self._report(
                item,
                "/body",
                "3.7",
                f"a relative link stays in one collection; use a typed reference: {destination}",
                line,
                severity=self.severity,
            )
            return None
        if fragment and fragment not in self._heading_ids(target_item):
            self._report(
                item,
                "/body",
                "3.7",
                f"no heading {fragment!r} in {target_item.raw.path}",
                line,
                severity=self.severity,
            )
            return None
        return ResolvedReference(
            kind=target_item.kind,
            target=target_item.path,
            label=label,
            href=_with_fragment(
                self._route(target_item.kind, target_item.path, target_item.collection), fragment
            ),
        )

    # -- the fourth destination form, section 3.7 ----------------------------

    def _is_repository_file(self, item: ParsedDocument, destination: str) -> bool:
        """Whether a destination names a repository path that is not content.

        A document of this repository is content and resolves as a reference; a
        path the checkout holds and no collection claims is a repository file.
        The lookup goes to the checkout rather than to the visible tree, so a
        path `ignore` hides from every collection is a repository file and not
        the unresolved asset the ruling of section 3.6 makes it.
        """

        resolved = self._repository_path(item, destination)
        return resolved is not None and resolved not in self.by_document

    def _repository_href(self, item: ParsedDocument, destination: str) -> str | None:
        """The hosting URL of a repository file, or None without one."""

        resolved = self._repository_path(item, destination)
        if resolved is None or not self.hosting_url:
            return None
        _, _, fragment = destination.partition("#")
        return _with_fragment(f"{self.hosting_url}/{resolved}", fragment)

    def _repository_path(self, item: ParsedDocument, destination: str) -> str | None:
        """The repository path a destination names, when the checkout holds it."""

        if destination.startswith("/"):
            return None
        target, _, _ = destination.partition("#")
        target = target.split("?")[0]
        if not target:
            return None
        resolved = _resolve_relative(item.raw.path, target)
        if not resolved:
            return None
        return resolved if (self.repository.root / resolved).exists() else None

    def _route(self, kind: str, target: str, collection: Collection) -> str:
        """Where a resolved target lives: the site's route, else the kind's."""

        if self.routes is not None:
            declared = self.routes(kind, target)
            if declared:
                return declared
        route = collection.kind.route
        return f"/{route(target)}" if route is not None else f"/{kind}/{target}"

    def _heading_ids(self, item: ParsedDocument) -> set[str]:
        """The heading ids of a target, as the rendered page carries them."""

        rendered = self.rendered.get(item.raw.path)
        if rendered is None:
            return set()
        return {str(heading["id"]) for heading in rendered[1]}

    # -- one asset, section 3.6 ----------------------------------------------

    def _asset(
        self, item: ParsedDocument, reference: str, pointer: str, line: int | None
    ) -> ResolvedAsset | None:
        problems = check_asset_reference(reference, pointer, line)
        if problems:
            for problem in problems:
                self.diagnostics.append(locate(item.raw.path, problem))
            return None
        if reference.startswith("https://"):
            return None
        target = reference.split("#")[0].split("?")[0]
        resolved = _resolve_relative(item.raw.path, target)
        if resolved is None:
            self._report(item, pointer, "3.6", f"asset leaves the repository: {target}", line)
            return None
        known = self.assets.get(resolved)
        if known is not None:
            return known
        defect = self.defects.get(resolved)
        if defect is None:
            defect = self._defect(resolved)
        if defect is not None:
            self.defects[resolved] = defect
            self._report(item, pointer, "3.6", defect, line)
            return None
        asset = self._upload(resolved)
        self.assets[resolved] = asset
        return asset

    def _defect(self, resolved: str) -> str | None:
        """Why this file may not be an asset (section 3.6), or None."""

        if not resolved.lower().endswith(ASSET_SUFFIXES):
            allowed = ", ".join(suffix.lstrip(".") for suffix in ASSET_SUFFIXES)
            return f"asset type is not allowed: {resolved}; allowed types are {allowed}"
        if resolved not in self.repository.files:
            reason = (
                "is ignored by content.yaml"
                if resolved in self.repository.ignored
                else "does not exist"
            )
            return f"asset {resolved} {reason}"
        size = self.repository.size(resolved)
        if size > MAX_ASSET_BYTES:
            return f"asset {resolved} is {size} bytes, over the {MAX_ASSET_BYTES} byte maximum"
        defect = asset_payload_defect(
            PurePosixPath(resolved).suffix, self.repository.read_bytes(resolved)
        )
        return None if defect is None else f"asset {resolved} is refused: {defect}"

    def _upload(self, resolved: str) -> ResolvedAsset:
        """Upload one referenced asset, and its dark sibling when paired."""

        dark = self._dark_sibling(resolved)
        return ResolvedAsset(
            path=resolved,
            url=self._url(resolved),
            dark_path=dark or "",
            dark_url=self._url(dark) if dark else "",
        )

    def _dark_sibling(self, resolved: str) -> str | None:
        if not self.manifest.theme_pairs:
            return None
        path = PurePosixPath(resolved)
        stem = path.with_suffix("")
        if stem.name.endswith(DARK_SUFFIX):
            # `name.dark.ext` is the dark half itself; it is never a light base,
            # so no `name.dark.dark.ext` is ever looked for.
            return None
        candidate = f"{stem}{DARK_SUFFIX}{path.suffix}"
        if candidate not in self.repository.files:
            return None
        return None if self._defect(candidate) is not None else candidate

    def _url(self, resolved: str) -> str:
        if self.media is None:
            return resolved
        checkout = (
            self.repository.checkout if self.repository.checkout is not None else self.repository
        )
        return self.media.upload(checkout, resolved, self.source).url

    # -- diagnostics ---------------------------------------------------------

    def _report(
        self,
        item: ParsedDocument,
        pointer: str,
        rule: str,
        message: str,
        line: int | None,
        severity: str = SEVERITY_ERROR,
    ) -> None:
        self.diagnostics.append(
            Diagnostic(item.raw.path, pointer, rule, message, severity=severity, line=line)
        )

    def _line(self, item: ParsedDocument, destination: str) -> int | None:
        """The body line a destination was written on, for a diagnostic.

        The rendered HTML carries no line numbers, so the source is searched for
        the destination as written. This locates a diagnostic; it never decides
        what the destination resolves to.
        """

        for number, line in enumerate(item.body.split("\n"), start=1):
            if destination in line:
                return item.body_line + number
        return None


# --- destinations -------------------------------------------------------------


def _names_an_asset(destination: str) -> bool:
    """Whether a destination names a file of an allowed asset type."""

    return destination.split("#")[0].split("?")[0].lower().endswith(ASSET_SUFFIXES)


def _is_external(destination: str) -> bool:
    if destination.startswith("//"):
        return True
    scheme = destination.split(":", 1)[0].lower() if ":" in destination else ""
    return scheme in EXTERNAL_SCHEMES


def _resolve_relative(source: str, target: str) -> str | None:
    """A destination relative to the referencing file, or None when it escapes."""

    base = PurePosixPath(source).parent
    parts: list[str] = list(base.parts)
    for part in PurePosixPath(target).parts:
        if part == ".":
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _with_fragment(href: str, fragment: str) -> str:
    return f"{href}#{fragment}" if fragment else href


def _reference_key_values(item: ParsedDocument) -> list[tuple[str, str]]:
    """Every typed reference written in front matter, with its pointer."""

    found: list[tuple[str, str]] = []
    for name, spec in item.part.keys.items():
        if spec.type not in ("reference", "reference_list"):
            continue
        value = item.data.get(name)
        if isinstance(value, str):
            found.append((f"/{name}", _qualify(value, spec.reference_kind)))
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            for index, entry in enumerate(value):
                if isinstance(entry, str):
                    found.append((f"/{name}/{index}", _qualify(entry, spec.reference_kind)))
    return found


def _qualify(value: str, fixed_kind: str | None) -> str:
    """Section 3.7: `authors`, `instructors` and `guests` omit the prefix."""

    if fixed_kind and not TYPED_REFERENCE_PATTERN.match(value.strip()):
        return f"{fixed_kind}:{value.strip()}"
    return value.strip()


# --- rewriting one tag --------------------------------------------------------


def _with_source(tag: str, url: str) -> str:
    return _SRC.sub(lambda match: f'src="{html_lib.escape(url, quote=True)}"', tag, count=1)


def _with_href(tag: str, url: str) -> str:
    return _HREF.sub(lambda match: f'href="{html_lib.escape(url, quote=True)}"', tag, count=1)


def _theme_pair(tag: str, asset: ResolvedAsset) -> str:
    """Both halves of a paired image, with the hooks a site styles.

    The two tags are adjacent with no whitespace between them, as in the AI
    Shipping Labs donor: the hidden half is out of the accessibility tree, so
    the shared `alt` is announced once.
    """

    light = _variant(tag, asset.url, "light")
    dark = _variant(tag, asset.dark_url, "dark")
    return f"{light}{dark}"


def _variant(tag: str, url: str, variant: str) -> str:
    hook = f"{THEME_FIGURE_CLASS} {THEME_FIGURE_CLASS}-{variant}"
    rewritten = _with_source(tag, url)
    found = _CLASS.search(rewritten)
    if found is None:
        rewritten = _TAG_END.sub(f' class="{hook}">', rewritten, count=1)
    else:
        existing = found.group(2)
        rewritten = (
            f'{rewritten[: found.start()]}class="{existing} {hook}"{rewritten[found.end() :]}'
        )
    return _TAG_END.sub(f' data-theme-figure="{variant}">', rewritten, count=1)
