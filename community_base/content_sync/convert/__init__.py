"""The one-off conversion of the content repositories to the format (C7.12).

Two scripts, one per repository family, both of them temporary:

    uv run python -m community_base.content_sync.convert.courses <path>
    uv run python -m community_base.content_sync.convert.documents <path> --profile <name>

`FORMAT.md` is what they convert to and `check_content` is what proves they
did. They exist for one pass over sixteen repositories and are deleted from
this package once the last conversion merges, which is issue `D7.4` step 9.
Nothing in the package imports them: they are entry points, not a capability.

Every script obeys two rules.

- It is idempotent. Running it over its own output changes nothing, so a
  conversion can be re-run after a content pull request lands during the
  freeze window.
- It never guesses. A construct it does not understand is refused, named in
  the report with the rule it failed, and left exactly as it was found. A
  conversion that silently drops content is worse than one that fails, so the
  report is a per-file inventory taken before and after, and every key it
  stops writing is printed with the value it had.
"""

from community_base.content_sync.convert.report import (
    ConversionReport,
    FileChange,
    Refusal,
)

__all__ = ["ConversionReport", "FileChange", "Refusal"]
