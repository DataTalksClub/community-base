"""Validators shared by curriculum models and their migrations.

Django serializes a field's validators by import path, so a migration that
validates a column keeps importing the module the callable lives in forever.
Keeping these callables out of the model module means a later model refactor
cannot break a historical migration.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

SHA1_PATTERN = r"^[0-9a-f]{40}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
REPOSITORY_COMPONENT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
REPOSITORY_BRANCH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$"
SOURCE_STABLE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"

sha1_validator = RegexValidator(SHA1_PATTERN, "Enter a full lowercase Git SHA.")
sha256_validator = RegexValidator(SHA256_PATTERN, "Enter a lowercase SHA-256 digest.")
source_stable_id_validator = RegexValidator(
    SOURCE_STABLE_ID_PATTERN,
    "Enter a canonical source stable ID.",
)
source_version_validator = RegexValidator(
    SOURCE_VERSION_PATTERN,
    "Enter a canonical source version.",
)
source_path_validator = RegexValidator(
    r"^(?!/)(?!.*\\).+$",
    "Enter a repository-relative POSIX path.",
)
repository_component_validator = RegexValidator(
    REPOSITORY_COMPONENT_PATTERN,
    "Enter a canonical repository owner or name.",
)
repository_branch_validator = RegexValidator(
    REPOSITORY_BRANCH_PATTERN,
    "Enter a canonical repository branch.",
)

MAX_SOURCE_PATH_CHARS = 1024


def validate_source_path(value: str) -> None:
    """Require a normalized repository-relative POSIX path."""

    if not value or value.startswith("/") or "\\" in value:
        raise ValidationError("Enter a repository-relative POSIX path.")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValidationError("Enter a normalized repository-relative POSIX path.")
    if PurePosixPath(value).as_posix() != value:
        raise ValidationError("Enter a normalized repository-relative POSIX path.")


__all__ = [
    "MAX_SOURCE_PATH_CHARS",
    "REPOSITORY_BRANCH_PATTERN",
    "REPOSITORY_COMPONENT_PATTERN",
    "SHA1_PATTERN",
    "SHA256_PATTERN",
    "SOURCE_STABLE_ID_PATTERN",
    "SOURCE_VERSION_PATTERN",
    "repository_branch_validator",
    "repository_component_validator",
    "sha1_validator",
    "sha256_validator",
    "source_path_validator",
    "source_stable_id_validator",
    "source_version_validator",
    "validate_source_path",
]
