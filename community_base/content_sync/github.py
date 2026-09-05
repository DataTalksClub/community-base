"""GitHub App client and safe immutable repository checkout."""

from __future__ import annotations

import re
import tarfile
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath

import jwt
import requests

from community_base.content_sync.checkout import CheckoutError, ImmutableCheckout
from community_base.kernel import conf

REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class GitHubClientError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, *, session=None):
        self.api_url = str(conf.get("CONTENT_SYNC_GITHUB_API_URL")).rstrip("/")
        self.app_id = str(conf.get("CONTENT_SYNC_GITHUB_APP_ID"))
        self.installation_id = str(conf.get("CONTENT_SYNC_GITHUB_INSTALLATION_ID"))
        self.private_key = str(conf.get("CONTENT_SYNC_GITHUB_PRIVATE_KEY"))
        self.timeout = int(conf.get("CONTENT_SYNC_HTTP_TIMEOUT"))
        self.max_archive_bytes = int(conf.get("CONTENT_SYNC_MAX_ARCHIVE_BYTES"))
        self.session = session or requests.Session()

    def resolve_commit(self, repo_name, ref="HEAD", *, private=False):
        self._validate_repository(repo_name)
        response = self._request(
            "GET",
            f"/repos/{repo_name}/commits/{ref}",
            private=private,
        )
        try:
            commit_sha = response.json()["sha"]
        except (KeyError, TypeError, ValueError):
            raise GitHubClientError("GitHub returned an invalid commit response") from None
        if not isinstance(commit_sha, str) or not COMMIT_PATTERN.fullmatch(commit_sha):
            raise GitHubClientError("GitHub returned an invalid commit SHA")
        return commit_sha

    def download_archive(self, repo_name, commit_sha, destination, *, private=False):
        self._validate_repository(repo_name)
        if not COMMIT_PATTERN.fullmatch(commit_sha):
            raise GitHubClientError("Invalid GitHub commit SHA")
        response = self._request(
            "GET",
            f"/repos/{repo_name}/tarball/{commit_sha}",
            private=private,
            stream=True,
        )
        size = 0
        with Path(destination).open("wb") as output:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > self.max_archive_bytes:
                    raise CheckoutError("GitHub archive exceeds configured size limit")
                output.write(chunk)

    def _request(self, method, path, *, private, stream=False):
        headers = {"Accept": "application/vnd.github+json"}
        token = self._installation_token(required=private)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self.session.request(
                method,
                f"{self.api_url}{path}",
                headers=headers,
                timeout=self.timeout,
                stream=stream,
            )
        except requests.RequestException:
            raise GitHubClientError("GitHub request failed") from None
        if not 200 <= response.status_code < 300:
            raise GitHubClientError(f"GitHub request failed with status {response.status_code}")
        return response

    def _installation_token(self, *, required):
        configured = (self.app_id, self.installation_id, self.private_key)
        if not all(configured):
            if required:
                raise GitHubClientError("GitHub App credentials are required for a private source")
            if any(configured):
                raise GitHubClientError("GitHub App credentials are incomplete")
            return ""
        now = int(time.time())
        app_token = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.app_id},
            self.private_key,
            algorithm="RS256",
        )
        try:
            response = self.session.request(
                "POST",
                f"{self.api_url}/app/installations/{self.installation_id}/access_tokens",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {app_token}",
                },
                timeout=self.timeout,
            )
        except requests.RequestException:
            raise GitHubClientError("GitHub App authentication failed") from None
        if not 200 <= response.status_code < 300:
            raise GitHubClientError(
                f"GitHub App authentication failed with status {response.status_code}"
            )
        try:
            token = response.json()["token"]
        except (KeyError, TypeError, ValueError):
            raise GitHubClientError("GitHub App returned an invalid token response") from None
        if not isinstance(token, str) or not token:
            raise GitHubClientError("GitHub App returned an invalid token response")
        return token

    @staticmethod
    def _validate_repository(repo_name):
        if (
            not isinstance(repo_name, str)
            or not REPOSITORY_PATTERN.fullmatch(repo_name)
            or any(part in {".", ".."} for part in repo_name.split("/"))
        ):
            raise GitHubClientError("Invalid GitHub repository name")


@contextmanager
def checkout_repository(source, *, client=None, commit_sha=None):
    client = client or GitHubClient()
    commit_sha = commit_sha or client.resolve_commit(source.repo_name, private=source.is_private)
    if not COMMIT_PATTERN.fullmatch(commit_sha):
        raise GitHubClientError("Invalid GitHub commit SHA")
    with ExitStack() as stack:
        workspace = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="cb-github-")))
        archive = workspace / "source.tar.gz"
        extracted = workspace / "repository"
        extracted.mkdir()
        client.download_archive(
            source.repo_name,
            commit_sha,
            archive,
            private=source.is_private,
        )
        _extract_archive(
            archive,
            extracted,
            max_files=source.max_files,
            max_bytes=client.max_archive_bytes,
        )
        checkout = stack.enter_context(
            ImmutableCheckout(extracted, commit_sha=commit_sha, max_files=source.max_files)
        )
        yield checkout


def _extract_archive(archive_path, destination, *, max_files, max_bytes):
    file_count = 0
    extracted_bytes = 0
    try:
        archive = tarfile.open(archive_path, mode="r:gz")
    except (OSError, tarfile.TarError):
        raise CheckoutError("GitHub returned an invalid repository archive") from None
    with archive:
        members = archive.getmembers()
        paths = [PurePosixPath(member.name) for member in members if member.name]
        if any(path.is_absolute() for path in paths):
            raise CheckoutError("GitHub archive contains an unsafe path")
        roots = {path.parts[0] for path in paths}
        if len(roots) != 1:
            raise CheckoutError("GitHub archive must contain one repository root")
        for member in members:
            parts = PurePosixPath(member.name).parts
            relative_parts = parts[1:]
            if not relative_parts:
                if not member.isdir():
                    raise CheckoutError("GitHub archive has an invalid repository root")
                continue
            if any(part in {"", ".", ".."} for part in relative_parts):
                raise CheckoutError("GitHub archive contains an unsafe path")
            target = Path(destination).joinpath(*relative_parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise CheckoutError("GitHub archive contains a link or special file")
            file_count += 1
            if file_count > max_files:
                raise CheckoutError(f"Checkout exceeds max_files={max_files}")
            extracted_bytes += member.size
            if extracted_bytes > max_bytes:
                raise CheckoutError("GitHub archive exceeds configured size limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.extractfile(member)
            if stream is None:
                raise CheckoutError("GitHub archive contains an unreadable file")
            with target.open("wb") as output:
                while chunk := stream.read(64 * 1024):
                    output.write(chunk)
