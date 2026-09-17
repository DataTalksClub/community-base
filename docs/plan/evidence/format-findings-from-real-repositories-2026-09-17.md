# Four format findings from parsing the eight real course repositories

Date: 2026-09-17. Raised by C7.10, which parsed all eight real course repositories read-only rather
than relying on fixtures. None blocked C7.10. The first will block C7.12 on every cohort it
converts, so it needs an answer before that issue starts.

## 1. The cohort title default is unreachable, and every real cohort needs it

Section 3.8 says a cohort's `title` defaults to `<course title> <identifier>`. Section 3.3 makes
`title` a required core key, and `register_kind` refuses a part that overrides a core key. So the
default can never be applied: a cohort manifest with no `title` is rejected before the parser sees
it.

Real cohort manifests carry no `title`. This will therefore fail on every cohort C7.12 converts.

Two ways out, and the choice is the owner's. Either section 3.3 gains an exemption letting a part
supply a default for a core key, or section 3.8 drops the default and the conversion writes a
`title` into every cohort manifest. The second is more files changed but keeps the core-key rule
absolute, which is the rule that has held the format together so far.

## 2. Archive is specified as a boolean and is not one in practice

Section 3.8 types `archive` as a boolean. Every real archived cohort carries a mapping,
`archive: {notice_path: ...}`, and two of the seventeen point at `cohorts/<year>/leaderboard.md`
rather than `README.md`.

The format only ever reads a cohort's `README.md` as its notice, so converting those two loses
which file the notice actually is. Either `archive` becomes a mapping with an optional notice path,
or the conversion moves those two notices into `README.md` and the information is deliberately
discarded.

## 3. A course's non-content relative links have no destination form

Sections 3.6 and 3.7 describe three destinations: a relative file inside the collection, a typed
`kind:slug`, and an external URL. Real lesson bodies link to none of those. They link to `code/`,
to `.py` and `.ipynb` files under `code/` and `embed/`, and to `../cohorts/<year>/`.

The course layout deliberately ignores those files, so they are not documents and not assets. Under
the default `strict_references: true` every such link is an unresolved reference and fails the
sync. This is why C7.10 does not call `resolve_repository` for courses.

The format needs either a fourth destination form for a file that lives in the repository but is
not content, or an explicit statement that such links are rewritten to the repository's hosting URL.
Until one exists, course asset and reference resolution cannot be switched on.

## 4. An empty placement and an absent placement are indistinguishable

Not a specification error, a consequence. An `archive: true` cohort parses to the empty placement
the format asks for, but an empty placement and an absent placement both leave zero `CohortModule`
rows, so the archived cohort still displays the course's full tree.

Separating the two needs a column on `Cohort`, which reopens the C5.1e placement contract that
C7.10 was told not to touch. Recorded in the curriculum README under known limitations. It wants an
issue of its own before D7.3 ships archived cohorts.
