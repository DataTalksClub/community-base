"""A site kind registered from outside the package, for `--kinds`.

This is what `AppConfig.ready()` does on a site: import a module that calls
`register_kind`. The validator's `--kinds` flag imports the same module when it
runs without Django.
"""

from community_base.content_sync.kinds import KeySpec, KindSpec, is_registered, register_kind
from community_base.content_sync.kinds.layouts import ItemDirectoryLayout

SPEC = KindSpec(
    name="podcast",
    shape="manifest",
    layout=ItemDirectoryLayout(part="podcast", document="episode.yaml"),
    keys={"guests": KeySpec("reference_list", reference_kind="person")},
    requires_date=True,
    route=lambda path: f"podcast/{path}",
)

if not is_registered("podcast"):
    register_kind("podcast", SPEC)
