import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote

from django.core.exceptions import ImproperlyConfigured

from community_base.kernel import conf


@dataclass(frozen=True)
class MediaResult:
    path: str
    url: str


class NullMediaStore:
    """Default media boundary that leaves authored paths unchanged."""

    def upload(self, checkout, path, source):
        checkout.read_bytes(path)
        return MediaResult(str(path), str(path))


class MediaStoreError(RuntimeError):
    pass


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
