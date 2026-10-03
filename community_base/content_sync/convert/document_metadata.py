"""Front matter and YAML metadata projection, with one unknown-key policy."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from community_base.content_sync.convert.article_profile import (
    ARTICLE_KEYS,
    prepare_metadata,
    preserve_extra,
)
from community_base.content_sync.convert.contracts import CORE_ORDER, DATE_NAME, Collection, Refused
from community_base.content_sync.convert.document_body import _relative_to
from community_base.content_sync.convert.report import ordered


class MetadataConversion:
    def __init__(self, namespace: uuid.UUID, known_slugs: set[str], profile_name: str = "") -> None:
        self.namespace = namespace
        self.known_slugs = known_slugs
        self.profile_name = profile_name

    def values(self, collection, page, target, titles, slugs) -> tuple[dict[str, Any], list[str]]:
        data = dict(page["front"])
        details: list[str] = []
        if self.profile_name == "dtc-articles":
            prepare_metadata(page, data, details)
        else:
            for old, new in collection.rename.items():
                if old in data and new not in data:
                    data[new] = data.pop(old)
                    details.append(f"{old} -> {new}")
        links = self._links(collection, data, details)
        if links:
            data["links"] = links
        if collection.date_from_name and self.profile_name != "dtc-articles":
            data["date"] = self._date(page, data, details)
        self._references(collection, page, data, titles, slugs, details)
        self._identity(collection, data, target, details)
        known = {*CORE_ORDER, *collection.keep, *collection.rename.values(), "extra", "links"}
        known |= set(collection.title_references) | set(collection.slug_references)
        if self.profile_name == "dtc-articles":
            preserve_extra(data, known, details)
            order = (*CORE_ORDER, *ARTICLE_KEYS, "links", "related", "extra")
        else:
            _extra(collection, data, known, details)
            order = (*CORE_ORDER, "links", "related", "extra")
        return ordered(data, order), details

    def _references(self, collection, page, data, titles, slugs, details) -> None:
        for name in collection.title_references:
            if name in data:
                data[name] = self._typed(page, name, data[name], titles, "title")
                details.append(f"{name}: titles -> {collection.kind}: references")
        for name in collection.slug_references:
            if name in data:
                data[name] = self._typed(
                    page, name, data[name], {slug: slug for slug in slugs}, "slug"
                )
                details.append(f"{name}: slugs -> {collection.kind}: references")

    def _identity(self, collection, data, target, details) -> None:
        image = str(data.get("image") or "").strip()
        if image:
            data["image"] = self._asset(collection, image, target, details)
        if not data.get("content_id"):
            data["content_id"] = str(uuid.uuid5(self.namespace, target))
            details.append(f"minted content_id from the repository namespace and {target}")
        if not str(data.get("title") or "").strip():
            raise Refused("3.3", "required key title is missing")

    def _asset(self, collection: Collection, value: str, target: str, details: list[str]) -> str:
        """An asset reference after its directory moved, relative to the item."""

        if value.startswith("https://"):
            return value
        if value != value.strip() or " " in value.split("/")[-1].strip():
            raise Refused("3.6", f"the asset path carries a stray space: {value!r}")
        moved = value.lstrip("/")
        for source, destination in collection.assets.items():
            if moved.startswith(f"{source}/"):
                moved = f"{destination}/{moved[len(source) + 1 :]}"
                break
        else:
            # Not a directory the collection moves. It is still a repository
            # path when its first segment is one the profile names; anything
            # else is relative to the file and stays as it was written.
            if moved.split("/")[0] not in collection.absolute_roots:
                return value
        relative = _relative_to(moved, target)
        if relative != value:
            details.append(f"image: {value!r} -> {relative!r}")
        return relative

    def _links(
        self, collection: Collection, data: dict[str, Any], details: list[str]
    ) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for label, name in collection.link_keys.items():
            value = data.pop(name, None)
            if not value:
                continue
            url = _profile_url(label, str(value).strip())
            if url.startswith("http://"):
                raise Refused("3.8", f"{name} is an http:// URL and the format takes https only")
            found.append({"label": label, "url": url})
            details.append(f"{name} -> links/{label}")
        return found

    def _date(self, page: Mapping[str, Any], data: Mapping[str, Any], details: list[str]) -> str:
        written = data.get("date")
        if written:
            return str(written)[:10]
        match = DATE_NAME.match(Path(str(page["source"])).name)
        if match is None:
            raise Refused("3.3", "required key date is missing and the name carries none")
        century = match.group("century") or "20"
        found = f"{century}{match.group('year')}-{match.group('month')}-{match.group('day')}"
        details.append(f"took date from the file name: {found}")
        return found

    def _typed(
        self,
        page: Mapping[str, Any],
        name: str,
        value: Any,
        index: Mapping[str, str],
        what: str,
    ) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise Refused("3.7", f"{name} is a list of {what}s")
        found: list[str] = []
        for entry in value:
            written = str(entry).strip()
            slug = index.get(written.lower()) or index.get(written)
            if slug is None and written in self.known_slugs:
                # A `related:` list that mixes titles and slugs, which the
                # podwiki does. A slug that names a page resolves as itself.
                slug = written
            if slug is None:
                raise Refused(
                    "3.7", f"{name} names {entry!r} and no page of this collection has that {what}"
                )
            found.append(f"wiki:{slug}")
        return found

    def yaml_values(
        self, collection: Collection, loaded: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        data = dict(loaded)
        details: list[str] = []
        for old, new in collection.rename.items():
            if old in data:
                data[new] = data.pop(old)
                details.append(f"{old} -> {new}")
        known = {*CORE_ORDER, *collection.keep, *collection.rename.values(), "extra"}
        _extra(collection, data, known, details)
        return ordered(data, (*CORE_ORDER, "extra")), details


def _profile_url(label: str, value: str) -> str:
    if value.startswith("http"):
        return value
    return {
        "linkedin": f"https://www.linkedin.com/in/{value}/",
        "github": f"https://github.com/{value}",
        "x": f"https://x.com/{value}",
        "youtube": f"https://www.youtube.com/@{value}",
    }.get(label, value)


def _extra(collection, data, known, details) -> None:
    extra = dict(data.get("extra") or {})
    for name in list(data):
        if name in known:
            continue
        if name in collection.drop:
            details.append(f"dropped {name}: {data[name]!r}")
            data.pop(name)
            continue
        extra[name] = data.pop(name)
        details.append(f"{name} -> extra")
    if extra:
        data["extra"] = extra
