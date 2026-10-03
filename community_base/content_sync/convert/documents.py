"""Convert document collections with one discovery pass and staged output plan.

Public profile declarations and entry points remain available here. Conversion
refusals preserve their source bytes; filesystem writes start after discovery.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import yaml

from community_base.content_sync.convert.contracts import (
    PROFILES,
    SLUG_OK,
    Collection,
    Profile,
    Refused,
)
from community_base.content_sync.convert.document_body import BodyConversion
from community_base.content_sync.convert.document_collections import (
    DocumentCollections,
    _jekyll_urls,
)
from community_base.content_sync.convert.document_metadata import MetadataConversion
from community_base.content_sync.convert.document_output import DocumentOutput
from community_base.content_sync.convert.report import (
    ConversionReport,
    dump_yaml,
    inventory,
    write_front_matter,
)

__all__ = ["PROFILES", "Collection", "Profile", "convert_documents", "main"]


def convert_documents(root: Path, profile: Profile, *, apply: bool = True) -> ConversionReport:
    """Convert the document collections of `root` in place and report on it."""
    root = Path(root)
    report = ConversionReport(repository=profile.name, before=inventory(root))
    _Conversion(root, profile, report, apply=apply).run()
    report.after = inventory(root)
    return report


class _Conversion:
    def __init__(
        self, root: Path, profile: Profile, report: ConversionReport, *, apply: bool
    ) -> None:
        self.root = root
        self.profile = profile
        self.namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"datatalksclub:{profile.name}")
        self.output = DocumentOutput(root, profile, report, apply)
        self.collections = DocumentCollections(root, profile, self.output)

    def run(self) -> None:
        for collection in self.profile.collections:
            self._convert_collection(collection)
        self.output.write_manifest()
        self.output.account()
        self.output.flush()

    def _convert_collection(self, collection: Collection) -> None:
        if collection.layout == "declare":
            return
        if collection.layout == "yaml":
            self._convert_yaml_collection(collection)
            return
        if collection.layout in ("data", "opaque"):
            if self.output.move_single_file(collection):
                return
        directory = self.collections.directory(collection)
        if directory is None:
            return
        if collection.layout in ("data", "opaque"):
            self.output.move_verbatim(collection, directory)
            return
        self._convert_pages(collection, directory)

    def _convert_pages(self, collection: Collection, directory: Path) -> None:
        pages = self.collections.pages(collection, directory)
        titles = {}
        slugs = set()
        for page in pages:
            titles[str(page["front"].get("title") or "").strip().lower()] = page["slug"]
            slugs.add(page["slug"])
        self.collections.place(collection, pages)
        urls = {}
        if collection.jekyll_urls:
            urls = _jekyll_urls(collection, pages)
        metadata = MetadataConversion(self.namespace, slugs, self.profile.name)
        body = BodyConversion(urls, self.profile.name)
        landing = {}
        for page in pages:
            try:
                self._convert_page(collection, page, titles, slugs, landing, metadata, body)
            except Refused as refusal:
                self.output.refuse_page(page["source"], refusal.rule, refusal.message)
        for source, target in collection.assets.items():
            self.output.move_assets(source, target)

    def _convert_page(self, collection, page, titles, slugs, landing, metadata, body) -> None:
        source = str(page["source"])
        slug = str(page["slug"])
        if not SLUG_OK.match(slug):
            raise Refused("3.4", f"the name does not reduce to a slug: {slug!r}")
        target = self.collections.target(collection, page, slug)
        if target in landing:
            raise Refused("3.4", f"two files land on {target}: this one and {landing[target]}")
        landing[target] = source
        page = {**page, "target": target}
        values, details = metadata.values(collection, page, target, titles, slugs)
        text, body_details = body.convert(collection, page, titles, slugs)
        self.output.put(source, target, write_front_matter(values, text), [*details, *body_details])

    def _convert_yaml_collection(self, collection: Collection) -> None:
        metadata = MetadataConversion(self.namespace, set())
        for path in self.collections.yaml_paths(collection):
            source = path.relative_to(self.root).as_posix()
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                self.output.refuse_page(source, "3.2", "a manifest is a mapping")
                continue
            values, details = metadata.yaml_values(collection, loaded)
            self.output.put(source, source, dump_yaml(values), details)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m community_base.content_sync.convert.documents",
        description="Convert a document collection to the content format, in place.",
    )
    parser.add_argument("path", help="the repository to convert")
    parser.add_argument("--profile", required=True, choices=sorted(PROFILES), help="the repository")
    parser.add_argument("--dry-run", action="store_true", help="run every rule and write nothing")
    options = parser.parse_args(argv)
    report = convert_documents(
        Path(options.path), PROFILES[options.profile], apply=not options.dry_run
    )
    sys.stdout.write(report.render())
    if report.ok:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
