"""The media boundary: where a referenced asset is checked and uploaded.

`FORMAT.md` section 3.6 requires signature and unsafe-SVG checks on every asset
before it is uploaded. :func:`asset_payload_defect` is that gate, lifted from
DataTalksClub's ``content/sync_parsers/media.py:media_payload_defect`` and
widened to the two asset types the format allows and the donor never served,
``webp`` and ``pdf``. The document toolkit calls it; a parser that uploads
through a store here gets the same refusal.
"""

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote

from django.core.exceptions import ImproperlyConfigured

from community_base.kernel import conf

#: The donor's unsafe-SVG scan, verbatim.
_UNSAFE_SVG = re.compile(
    r"<script\b|<style\b|<!doctype|<!entity|expression\s*\(|"
    r"url\s*\(\s*['\"]?(?:https?:|//|data:)|"
    r"\bon[a-z]+\s*=|\b(?:href|src)\s*=\s*['\"](?:https?:|//|data:)"
)


def asset_payload_defect(suffix: str, payload: bytes) -> str | None:
    """Why these bytes may not be uploaded under that suffix, or None.

    The signature rules are the donor's: a file whose extension and bytes
    disagree never reaches a media store, and an SVG carrying script, style,
    external references or event handlers is refused outright rather than
    sanitized, because nothing renders it before a browser does.
    """

    suffix = suffix.lower()
    if suffix in (".jpg", ".jpeg") and not (
        payload.startswith(b"\xff\xd8\xff") and payload.endswith(b"\xff\xd9")
    ):
        return "JPEG signature mismatch"
    if suffix == ".png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG signature mismatch"
    if suffix == ".gif" and not payload.startswith((b"GIF87a", b"GIF89a")):
        return "GIF signature mismatch"
    if suffix == ".webp" and not (payload.startswith(b"RIFF") and payload[8:12] == b"WEBP"):
        return "WEBP signature mismatch"
    if suffix == ".pdf" and not payload.startswith(b"%PDF-"):
        return "PDF signature mismatch"
    if suffix == ".svg":
        try:
            svg = payload.decode("utf-8")
        except UnicodeDecodeError:
            return "SVG is not UTF-8"
        lowered = svg.casefold()
        if "<svg" not in lowered[:1000] or _UNSAFE_SVG.search(lowered):
            return "unsafe SVG"
    return None


@dataclass(frozen=True)
class MediaResult:
    path: str
    url: str


class MediaStoreError(RuntimeError):
    pass


def _null_media_url(path) -> str:
    """Derive a site-absolute URL for a path the null store does not upload."""

    relative = PurePosixPath(str(path))
    if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
        raise MediaStoreError("Unsafe media path")
    prefix = str(conf.get("CONTENT_SYNC_NULL_MEDIA_URL_PREFIX")).strip("/")
    parts = tuple(part for part in (prefix, relative.as_posix()) if part)
    return "/" + quote("/".join(parts), safe="/")


class NullMediaStore:
    """Default media boundary that uploads nothing and links back to the site.

    The store has no storage of its own, so the stored path stays the authored
    repository path.  The URL cannot: the sanitiser admits an ``img src`` only
    when it is site-absolute or an absolute ``http(s)`` URL, so returning the
    bare repository path made every site on the default backend store synced
    images with a source the renderer then dropped, and nothing said so until
    someone looked at a page (D37).  The URL is therefore the repository path
    under ``CONTENT_SYNC_NULL_MEDIA_URL_PREFIX``.

    Serving that prefix is the site's job.  The package guarantees only that the
    URL is shaped so the renderer keeps it; a site that maps the prefix at no
    route gets a 404 it can see, which is the point -- an invisible failure is
    traded for a visible one.
    """

    def upload(self, checkout, path, source):
        checkout.read_bytes(path)
        return MediaResult(str(path), _null_media_url(path))


class S3MediaStore:
    def __init__(self, *, client=None):
        self.bucket = str(conf.get("CONTENT_SYNC_S3_BUCKET"))
        self.prefix = str(conf.get("CONTENT_SYNC_S3_PREFIX")).strip("/")
        self.public_url = str(conf.get("CONTENT_SYNC_S3_PUBLIC_URL")).rstrip("/")
        self.region = str(conf.get("CONTENT_SYNC_S3_REGION"))
        if not self.bucket:
            raise ImproperlyConfigured(
                "CONTENT_SYNC_S3_BUCKET is required for the S3 media backend"
            )
        if any(part in {".", ".."} for part in PurePosixPath(self.prefix).parts):
            raise ImproperlyConfigured("CONTENT_SYNC_S3_PREFIX contains an unsafe path")
        self.client = client or self._client()

    def _client(self):
        try:
            import boto3
        except ImportError:
            raise ImproperlyConfigured(
                "The S3 media backend requires the community-base[s3] extra"
            ) from None
        options = {"region_name": self.region} if self.region else {}
        return boto3.client("s3", **options)

    def upload(self, checkout, path, source):
        payload = checkout.read_bytes(path)
        digest = hashlib.sha256(payload).hexdigest()
        relative = PurePosixPath(str(path))
        key_parts = tuple(
            part for part in (self.prefix, source.slug, digest, relative.as_posix()) if part
        )
        key = "/".join(key_parts)
        content_type = mimetypes.guess_type(relative.name)[0] or "application/octet-stream"
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentType=content_type,
                Metadata={"sha256": digest},
            )
        except Exception:
            raise MediaStoreError("S3 media upload failed") from None
        if self.public_url:
            url = f"{self.public_url}/{quote(key, safe='/')}"
        else:
            url = f"s3://{self.bucket}/{key}"
        return MediaResult(str(path), url)


def media_store():
    backend = conf.get("CONTENT_SYNC_MEDIA_BACKEND")
    if backend == "null":
        return NullMediaStore()
    if backend == "s3":
        return S3MediaStore()
    raise ImproperlyConfigured(f"Unsupported content sync media backend: {backend}")
