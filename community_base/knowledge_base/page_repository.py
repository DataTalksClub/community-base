"""One shared read and resolution view for package knowledge-base parsers."""

from community_base.content_sync.documents import ReadResult, read_repository
from community_base.content_sync.resolution import (
    ResolutionResult,
    ResolvedDocument,
    hosting_url_for,
    resolve_repository,
)
from community_base.knowledge_base.routes import route_resolver


class RepositoryView:
    """Read and resolve one checkout once for all package knowledge-base kinds."""

    def __init__(self, checkout, source) -> None:
        self.checkout = checkout
        self.commit_sha = str(getattr(checkout, "commit_sha", "") or "")
        self.source = source
        self.read: ReadResult = read_repository(checkout)
        declared = []
        for collection in self.read.manifest.collections:
            declared.append(collection.kind.name)
        self.declared = frozenset(declared)
        self._resolved: ResolutionResult | None = None
        self._by_path: dict[str, ResolvedDocument] = {}

    def resolve(self, media) -> ResolutionResult:
        if self._resolved is None:
            self._resolved = resolve_repository(
                self.read,
                media=media,
                source=self.source,
                routes=route_resolver(self.declared),
                hosting_url=hosting_url_for(self.source, self.commit_sha),
            )
            self._by_path = self._resolved.by_path()
        return self._resolved

    def document(self, media, source_path: str) -> ResolvedDocument:
        self.resolve(media)
        return self._by_path[source_path]

    def read_errors(self) -> tuple[str, ...]:
        rendered = []
        for item in self.read.errors:
            rendered.append(item.render())
        return tuple(rendered)


_last_view: tuple[tuple[str, str, str], RepositoryView] | None = None


def repository_view(checkout, source) -> RepositoryView:
    """Return the cached view shared by adjacent parsers of one sync."""

    global _last_view
    key = (
        str(getattr(checkout, "root", "")),
        str(getattr(checkout, "commit_sha", "")),
        str(source),
    )
    if _last_view is not None and _last_view[0] == key:
        return _last_view[1]
    view = RepositoryView(checkout, source)
    _last_view = (key, view)
    return view
