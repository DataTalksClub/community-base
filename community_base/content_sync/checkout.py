"""Immutable, no-symlink snapshots for untrusted content repositories."""

import hashlib
import os
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


class CheckoutError(RuntimeError):
    pass


class ImmutableCheckout:
    def __init__(self, root, *, commit_sha="", max_files=1000):
        self.source_root = Path(os.path.abspath(os.fspath(root)))
        self.commit_sha = commit_sha
        self.max_files = max_files
        self._temporary = None
        self.root = None
        self._manifest = {}

    def __enter__(self):
        try:
            root_mode = self.source_root.lstat().st_mode
        except OSError:
            raise CheckoutError("Checkout root is missing or is not a directory") from None
        if not stat.S_ISDIR(root_mode) or stat.S_ISLNK(root_mode):
            raise CheckoutError("Checkout root is missing or is not a directory")
        self._temporary = tempfile.TemporaryDirectory(prefix="community-base-content-")
        self.root = Path(self._temporary.name)
        self._snapshot_directory(self.source_root)
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._temporary.cleanup()

    def _snapshot_directory(self, source_root):
        count = 0
        for current, directories, files in os.walk(source_root, followlinks=False):
            current_path = Path(current)
            relative_directory = current_path.relative_to(source_root)
            safe_directories = []
            for name in sorted(directories):
                path = current_path / name
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    raise CheckoutError(f"Symlink is not allowed: {path.relative_to(source_root)}")
                if name == ".git":
                    continue
                if not stat.S_ISDIR(mode):
                    raise CheckoutError(
                        f"Non-directory checkout entry: {path.relative_to(source_root)}"
                    )
                safe_directories.append(name)
            directories[:] = safe_directories
            target_directory = self.root / relative_directory
            target_directory.mkdir(parents=True, exist_ok=True)
            for name in sorted(files):
                source_path = current_path / name
                relative_path = source_path.relative_to(source_root)
                mode = source_path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    raise CheckoutError(f"Symlink is not allowed: {relative_path}")
                if not stat.S_ISREG(mode):
                    raise CheckoutError(f"Non-regular file is not allowed: {relative_path}")
                count += 1
                if count > self.max_files:
                    raise CheckoutError(f"Checkout exceeds max_files={self.max_files}")
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                try:
                    descriptor = os.open(source_path, flags)
                except OSError:
                    raise CheckoutError(f"File changed during snapshot: {relative_path}") from None
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise CheckoutError(f"Non-regular file is not allowed: {relative_path}")
                    with os.fdopen(descriptor, "rb", closefd=False) as stream:
                        payload = stream.read()
                finally:
                    os.close(descriptor)
                target = self.root / relative_path
                target.write_bytes(payload)
                target.chmod(0o444)
                key = PurePosixPath(relative_path.as_posix())
                self._manifest[key.as_posix()] = hashlib.sha256(payload).hexdigest()
        for directory in sorted(self.root.rglob("*"), reverse=True):
            if directory.is_dir():
                directory.chmod(0o555)

    def files(self):
        return tuple(PurePosixPath(path) for path in sorted(self._manifest))

    def read_bytes(self, relative_path):
        path = self._validated_path(relative_path)
        payload = path.read_bytes()
        relative = PurePosixPath(str(relative_path)).as_posix()
        if hashlib.sha256(payload).hexdigest() != self._manifest.get(relative):
            raise CheckoutError(f"Immutable checkout changed: {relative}")
        return payload

    def read_text(self, relative_path, encoding="utf-8"):
        return self.read_bytes(relative_path).decode(encoding)

    def _validated_path(self, relative_path):
        pure = PurePosixPath(str(relative_path))
        if pure.is_absolute() or not pure.parts or any(part in {".", ".."} for part in pure.parts):
            raise CheckoutError("Path escapes checkout")
        normalized = pure.as_posix()
        if normalized not in self._manifest:
            raise CheckoutError(f"File is not in checkout manifest: {normalized}")
        return self.root.joinpath(*pure.parts)


def git_commit_sha(path):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    candidate = result.stdout.strip()
    if (
        result.returncode == 0
        and len(candidate) == 40
        and all(c in "0123456789abcdef" for c in candidate)
    ):
        return candidate
    return ""
