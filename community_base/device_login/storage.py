"""Owner-only JSON credentials: POSIX modes or private Windows file ACLs."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


def _windows_acl(path: Path, *, protect: bool = False) -> bool:
    """Set/check owner-only NTFS access; never pass credential content to a shell."""
    script = """
        $ErrorActionPreference = 'Stop'
        $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
        if ($env:CB_PRIVATE_ACTION -eq 'protect') {
            $acl = New-Object System.Security.AccessControl.FileSecurity
            $acl.SetOwner($sid)
            $acl.SetAccessRuleProtection($true, $false)
            $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
                $sid, 'FullControl', 'Allow')
            $acl.AddAccessRule($rule)
            [System.IO.File]::SetAccessControl($env:CB_PRIVATE_PATH, $acl)
        }
        $acl = [System.IO.File]::GetAccessControl($env:CB_PRIVATE_PATH)
        $allowed = @($sid.Value, 'S-1-5-18', 'S-1-5-32-544')
        $rules = $acl.GetAccessRules(
            $true, $true, [System.Security.Principal.SecurityIdentifier])
        $unsafe = @($rules | Where-Object {
            $_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Value -notin $allowed
        })
        if ($unsafe.Count -eq 0) { 'private' } else { 'shared' }
    """
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=dict(
            os.environ,
            CB_PRIVATE_PATH=str(path),
            CB_PRIVATE_ACTION="protect" if protect else "check",
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() == "private"


def _save_windows(target: Path, payload: dict) -> Path:
    # Restrict an empty temporary file BEFORE writing any credential. Replacing
    # the target publishes the complete file together with its private ACL.
    descriptor, name = tempfile.mkstemp(prefix=".credentials-", dir=target.parent)
    temporary = Path(name)
    os.close(descriptor)
    try:
        if not _windows_acl(temporary, protect=True):
            raise PermissionError("Could not restrict credential file permissions.")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(payload, output)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def save_private_json(path: str | Path, payload: dict) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        return _save_windows(target, payload)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    return target


def read_private_json(path: str | Path, *, enforce_mode: bool = True) -> dict:
    target = Path(path).expanduser()
    if target.is_symlink():
        raise PermissionError("Credential profile must not be a symbolic link.")
    if enforce_mode:
        private = _windows_acl(target) if os.name == "nt" else not (target.stat().st_mode & 0o077)
        if not private:
            raise PermissionError(
                f"Credential profile at {target} must be owner-only (0600 on POSIX)."
            )
    raw = target.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Credential profile is invalid.")
    return payload
