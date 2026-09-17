# D7.1 stop report: the released knowledge base app cannot hold DTC's wiki and docs

Date: 2026-09-17. Raised while starting D7.1 (DataTalksClub/website#406). No code was written;
the issue hit a stop condition in `docs/04-quality-gates.md` section 5 (the package lacks a
capability the site relies on). The remedy is the new package issue C7.4.

## What was checked

The analysis ran against the copy the site actually resolves, not against this repository's
working tree.

| Check | Result |
|---|---|
| `grep -n "community-base" ~/git/dtc-website/uv.lock` | pinned at `rev = "v0.4.7"` |
| `diff -r .venv/.../community_base/knowledge_base ~/git/community-base/community_base/knowledge_base` | identical |
| `community_base.knowledge_base` in DTC `INSTALLED_APPS` | not yet installed |

## Gap 1: the documentation tree cannot be stored

DTC's docs identity is a slash path, built in `content/sync_parsers/docs.py:175-179`
(`_stable_key` joins the path parts, dropping an `index` stem).

- `community_base/knowledge_base/models.py:37` sets `SLUG_PATTERN = r"^[-a-zA-Z0-9_.]+$"`,
  applied at `models.py:55`. A slash-bearing key is rejected, so the full path cannot be the slug.
- `community_base/knowledge_base/models.py:77-80` pins
  `UniqueConstraint(fields=("section", "slug"))`. Uniqueness is per section, not per parent, so
  the leaf segment cannot be the slug either.
- DTC's pinned `_docs/compatibility/generated-path-baseline.jsonl` holds 167 multi-segment
  `/docs/...` paths with 15 repeated leaf segments: `project` seven times, `curriculum` six,
  `environment-setup` six, `getting-started` six, `prerequisites` six, `resources` six,
  `whats-new` five, `qa` three, and seven more twice.

There is no third option. `sync.upsert_page` (`community_base/knowledge_base/sync.py:51-64`)
accepts no public path, and `models.py:103-105` derives the URL from the ancestor chain, while
DTC derives it from the source file path (`content/sync_parsers/docs.py:182-185`) and resolves
`parent` independently, by front-matter title (`content/sync_parsers/docs.py:66-77`). The app
collapses two independent inputs into one.

## Gap 2: the wiki page body has no representation

DTC wiki pages are not markdown. `content/sync_parsers/podwiki.py:380-395` stores `blocks`,
`tags`, `fragment_ids`, `unresolved_fragment_ids` and `relations`, and
`templates/public/wiki_detail.html:107,140,144` renders `record.relations`,
`record.unresolved_fragment_ids` and `record.blocks`.

`KnowledgeBasePage` has only `body` and `body_html` (`models.py:56-57`) and no JSON field.
`SourceProvenanceMixin` (`community_base/content_sync/provenance.py:38-59`) adds only
`source_content_id`, `source_path`, `source_commit_sha` and `source_checksum`.

Heading fragment ids are a checked contract, not decoration: `podwiki.py:363-374` fails the sync
when a fragment does not resolve uniquely.

## Gap 3: docs record metadata has no home

`content/docs_projection.py:646-663` (`_synced_page_record`) carries `edit_url`, `has_toc`,
`has_children`, `permalink`, `grand_parent`, `grand_parent_path` and `body_sha256`, plus the
declared `images` that drive `/docs/assets/...` (`content/docs_projection.py:642-676`,
`docs_asset_path` at `:409-430`). `edit_url` reaches a template at
`templates/review/docs_detail.html:165,173`. None of these has a field.

## Gap 4: rendering cannot be site-owned

`community_base/knowledge_base/models.py:93-101`: `save()` unconditionally sets
`body_html = render_markdown(...)` (python-markdown, `rendering.py:186-192`), and the field is
`editable=False`. DTC renders with mistune plus kramdown and liquid preprocessing and heading-id
injection, returning heading metadata for the table of contents
(`content/docs_projection.py:66,369-377,119-139,433-447`). The app README offers
`rendering.sanitize_rendered_html`, but there is no way to store the result.

## A plan error this also uncovered

D7.1 step 4 named `content/wiki_content.py` and `content/docs_presentation.py` as superseded
projection modules. Both are misccategorised, and step 2 of the same issue contradicts the
removal.

- `content/wiki_content.py` is the knowledge graph composition: `episode_graph`, `graph_groups`,
  `graph_totals`, `busiest_neighbourhood`, `WIKI_ASSET_ROOT`, consumed at
  `content/public_views.py:722,728,1027-1029` and `core/tests/test_graph_layout.py:15`. Step 2 and
  issue #406 both say the graph stays DTC-owned.
- `content/docs_presentation.py` is presentation: rails, hub, curriculum split, search snippets,
  consumed at `content/review_views.py:21-31` and `playwright_tests/test_docs_navigation.py:8`.
  Step 2 keeps templates and presentation in `content`.
- The wiki read model the issue never mentions is `content/catalogue.py:548-557`.

`docs/plan/phase-7.md` D7.1 has been corrected. Issue #406 needs the same correction.

## Test counts at risk, recorded for whoever resumes D7.1

Quality gate section 3 wants a before and after count. Only the before side exists so far.

| Location | `def test_` |
|---|---|
| `content/tests/test_docs_projection.py` | 30 |
| `content/tests/test_docs_pages.py` | 21 |
| `content/tests/test_wiki_design.py` | 46 |
| `content/tests/test_podcast_episode_graph.py` | 10 |
| `content/tests/test_podcast_stable_routes.py` | 9 |
| DTC total at risk | 116 |
| package `tests/knowledge_base/` today | 54 |

## Baseline verification run on the unchanged tree

    uv run --frozen python manage.py test content.tests.test_route_contracts \
      content.tests.test_sitemap_contract --parallel 4 --settings=website.settings.test
    -> Ran 12 tests, OK

    uv run --frozen python manage.py check
    -> System check identified no issues (0 silenced), exit 0

## Why A7.1 was not blocked by any of this

A7.1 gave AISL a wiki and docs it did not have before, authored to fit the app. D7.1 moves an
existing corpus with its own identity, rendering pipeline and record shape, and must not change a
single public path. The app was built against the first case.

## Addendum, 2026-09-17: D7.1 is implemented, and one packaging defect found on the way

C7.4 closed all four gaps and D7.1 is implemented on branch `d7.1-knowledge-base`. The route and
sitemap contracts pass unchanged, and `git diff origin/main -- content/route_contracts.py
content/sitemap_contract.py _docs/compatibility/` is empty, so the pinned inventories were not
edited to fit. The full-suite failure-set diff against a same-commit baseline is a single
order-dependent flake that fails on both sides.

Two things the adoption surfaced that belong to the release, not to D7.1.

### The v0.4.7 tag was moved after a consumer locked it

| Where | Commit | pyproject version |
|---|---|---|
| `refs/tags/v0.4.7` now, local and remote | `ab8e8ab` | 0.4.7 |
| what `dtc-website/uv.lock` resolved `v0.4.7` to | `e98c338` | 0.4.6 |

`e98c338` is `ab8e8ab`'s parent, and the only difference between them is the version string, so
there is no behavioural risk here. The process defect is real though: the tag was cut at a commit
that had not yet had its version bumped, a consumer locked that commit, and the tag was then moved
to the bump. A consumer that re-locks today gets different bytes than one that locked earlier,
which is exactly what pinning a tag is supposed to prevent (D1).

This explains an observation that otherwise looks like corruption: DTC's virtualenv carries
`community_base-0.4.6.dist-info` while its `direct_url.json` records `requested_revision: v0.4.7`.

The remedy is not to move the tag again. Cut the next release normally, with the version bump in
the tagged commit, and leave `v0.4.7` where it is.

### Bumping the DTC pin needs a mapping change in the same release-adoption issue

On unchanged `origin/main` with the package linked to community-base main,
`scripts.tests.test_import_shared_course_platform` fails 17 of its 18 tests on one `MappingCoverageDrift`
naming `cb_coursework.Project: pooled_review_window_days`, `cb_coursework.ProjectSubmission:
review_state` and `cb_coursework.PeerReview: batch`. Those are the C5.2f, C5.2g and C5.2h fields,
merged to main and still unreleased.

`scripts/prod/import_shared_course_platform.py:_mapping()` has to be extended in whatever change
bumps the pin. It is not a D7.1 defect and was not fixed there.
