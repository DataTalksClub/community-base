# Conversion runs against the real content repositories

Date: 2026-09-18. Produced by `C7.12`. Every run is against a `git archive` export of the real
repository into a scratch directory; no content repository was opened for writing. The actual
cutovers are `A7.3` and `D7.4`, each with a one-day content freeze on the repositories it converts.

The scripts are `community_base/content_sync/convert/courses.py` and
`community_base/content_sync/convert/documents.py`. Both are deleted after the last conversion
merges, which is `D7.4` step 9.

The runs below were taken after `C7.18` landed the code for decisions D38 and D39 in the same
branch. Without it no course repository resolves its references at all, so no course row in the
first table could have been produced.

## How to read the table

- Files: the count the inventory took before the conversion.
- Converted: files rewritten, renamed or created.
- Refusals: constructs the script would have had to guess at. A refused file is left exactly as it
  was found and named in the report with the rule it failed.
- `check_content`: `uv run python -m community_base.content_sync.check <path>` over the converted
  copy, with the package kinds alone.

Every run in the table is idempotent: the script was run a second time over a copy of its own
output and `diff -rq` reported no difference.

## The eight course repositories

| Repository | Files | Converted | Refusals | `check_content` |
|---|---|---|---|---|
| `DataTalksClub/llm-zoomcamp` | 572 | 91 | 0 | matches the content format version 1 |
| `DataTalksClub/data-engineering-zoomcamp` | 954 | 110 | 0 | matches the content format version 1 |
| `DataTalksClub/machine-learning-zoomcamp` | 1784 | 131 | 0 | matches the content format version 1 |
| `DataTalksClub/mlops-zoomcamp` | 518 | 59 | 0 | matches the content format version 1 |
| `DataTalksClub/ai-dev-tools-zoomcamp` | 241 | 16 | 0 | matches the content format version 1 |
| `DataTalksClub/stock-markets-analytics-zoomcamp` | 45 | 2 | 1 | 1 error |
| `AI-Shipping-Labs/python-course` | 143 | 46 | 0 | matches the content format version 1 |
| `AI-Shipping-Labs/ai-buildcamp-course` | 896 | 269 | 0 | 5 errors |

Six of the eight convert with no refusal and pass the validator with zero errors and zero warnings.

The two that do not are content the conversion will not author:

- `stock-markets-analytics-zoomcamp`: `course.yaml` carries no `description`, which section 3.8
  requires. The conversion refuses rather than writing one. An author writes a description before
  `D7.4` merges it. Its five `NN-` directories carry notebooks and a `README.md` and no
  `module.yaml`, so they are declared not-content in `content.yaml`, and the three `cohorts/<year>/`
  directories carry no `cohort.yaml` and are declared opaque archive; both are named in the report.
- `ai-buildcamp-course`: five links in
  `03-agentic-flows/06-tool-calling-with-alternative-providers/01-tool-calling-with-alternative-providers.md`
  name `.py` files that the `restructure-1675-maven-tree` tree does not hold; the files are under
  `source-v2/`, which the restructure left behind. The conversion reports every relative link that
  resolves to nothing rather than repairing one. This is the "confirm the restructure branch is the
  intended tree" item the specification's section 5 already records for this repository.

`ai-buildcamp-course` is also the one repository whose `cohorts:` list names a cohort with no
directory. The conversion writes `cohorts/4/cohort.yaml` from that entry, with a `content_id`
minted as a version 5 UUID of the course `content_id` and the identifier, so a second run writes the
same one.

## The document collections

Six profiles ship. `faq` uses the package kinds alone and therefore reports one error, `unknown
kind: faq`; that kind is registered by DataTalks.Club under decision D26 and the repository's own CI
passes `--kinds`.

| Repository | Files | Converted | Refusals | `check_content` |
|---|---|---|---|---|
| `AI-Shipping-Labs/wiki` | 116 | 20 | 0 | matches the content format version 1 |
| `DataTalksClub/podwiki` | 1768 | 394 | 16 | 895 errors |
| `DataTalksClub/datatalksclub.github.io` (`_people`) | 2655 | 868 | 21 | 44 errors |
| `DataTalksClub/content` (`articles`) | 1406 | 44 | 12 | 25 errors |
| `DataTalksClub/docs` | 285 | 105 | 2 | 16 errors |
| `DataTalksClub/faq` | 1618 | 1410 | 0 | 1 error |

What the refusals are, and who owns each:

- `podwiki`, 16 refusals: a page whose last code fence is opened and never closed. Everything after
  an unterminated fence is code to the renderer and to the conversion alike, so converting it would
  silently leave half the page as it was. The 895 validator errors are all links into those 16
  pages, which stay outside the collection until an author closes the fences. `D7.4` owns them.
- `dtc-people`, 21 refusals: an `http://` personal website, which section 3.8 does not take.
  Upgrading one to `https://` is a guess about somebody else's server. The 44 validator errors are
  `bio_short` values longer than the 500 characters section 3.3 allows for `summary`. `D7.4` owns
  both, and they are the file-level part of decision D25.
- `dtc-articles`, 12 refusals: a Liquid include the conversion does not read, which is
  `faq-accordion.html`, `course-structured-data/*.html` and one `{% raw %}`. The one include the
  format has a shape for, `youtube.html`, is converted to an `embed` fence (section 4.3). The 25
  validator errors are the five year directories still holding the twelve refused files, and
  nineteen absolute links into other DataTalks.Club repositories (`/podcast.html`,
  `/people/<id>.html`), which resolve at sync and not in one repository. `D7.2` and `D7.4` own them.
- `dtc-docs`, 2 refusals: the same unterminated fence. The 16 validator errors are ten links into
  those two pages and six brand-asset SVGs the asset check calls unsafe. `D7.4` owns them.

The twenty-five re-parented documentation pages of decision D28 are produced by the conversion, not
left to a human: the `docs` profile builds the tree from `parent:` and `grand_parent:` titles, so a
page whose parent is a sibling page moves into a directory that page now heads. `D7.4` step 5
updates `content/route_contracts.py` and `content/sitemap_contract.py` for exactly those paths.

## The three human-review concentrations

The specification's section 5 names three. Here is where each stands.

| Concentration | Owner | State after `C7.12` |
|---|---|---|
| The rendering diff of the 55 DataTalks.Club articles | `D7.2`, verified at `D7.4` | 43 convert; 12 refuse on a Liquid include the conversion does not read, each named in the report with its line |
| The 25 re-parented documentation pages (D28) | `D7.4` | produced by the conversion; the route and sitemap contracts are the review |
| The podwiki tokens whose title resolves to nothing | `D7.4` | none left unresolved: a `[[token]]` or a `related:` entry naming no page is a refusal, not a silent drop, and the 16 refusals this repository has are unterminated fences instead |

## Repositories whose kinds the package does not register

`aisl-content` and `aisl-workshops` now exist (`C7.12a`). Scratch copies converted on 2026-09-20:

- `aisl-content`: 21 renamed, 7 rewritten, `content.yaml` created, one refusal
  (`blog/what-is-an-ai-engineer-alexey-grigorev-perspective/...md`, `{% prompt %}` Liquid the
  conversion does not read). A second run rewrites nothing.
- `aisl-workshops`: 25 `workshop.yaml` rewritten (`instructor_name` to `byline`), `content.yaml`
  created, zero refusals. A second run rewrites nothing.

`check_content` on the converted copies still waits on `A7.2a` registering `workshop`, `project`,
`curated_link` and `interview_question`. The member-wiki storage ruling also stays `A7.2a`:
`aisl-wiki` still writes the package wiki kind.
