# Same-workspace and cross-workspace agent coordination, 2026-09-29

## Scope and observed state

This note records coordination between the `community-base` session
`fc19aa35-48b6-4a62-b984-8adbf55fa6c5` and AI Shipping Labs sessions in
`/home/alexey/git/ai-shipping-labs`. It records the coordination protocol,
implemented aplexer improvements and remaining proposals. It does not authorize a merge or deployment.
Session states and ownership below are snapshots, not locks.

- At the check, AISL `quality` (`63345d29-2ca9-4331-9804-729daa22d19d`) was
  running and reported idle. `release` (`2ae31921-a52d-4863-b020-70e3d6a80d32`)
  was running. `builcamp-conten` (`938b126c-909b-4da6-a322-682e86fce1e8`)
  was running and reported waiting. State can change between lookup and send.
- The user relayed AISL ownership: `home-fixes` at
  `/data/agents/ai-shipping-labs/worktrees/home-fixes`, HEAD `79032a68c`, is
  rebasing/pushing Home fixes and then mobile fixes. It owns the Home/module
  parts of `course_home`, `current_module`, `course_commitments`, `module_home`,
  `course_navigation`, `views/courses`, and Home/reader/homework steps/peer
  review/workshops/dashboard/Studio templates. Treat these as reserved until
  its owner releases them. Parser/backend outside those areas was reported free.
- The root's AISL issue-1842 work is in the leased worktree
  `/home/alexey/git/ai-shipping-labs/.claude/worktrees/agent-1842-course-simplification`
  on `worktree-agent-1842`, at `de0a85732` when reported. Shared main is
  read-only for that work. The AISL development deploy and package version pin
  are in separate, ongoing work; no deploy or push is inferred from this note.

## What the installed commands did before the candidate change

| Probe | Result | Meaning |
|---|---|---|
| `aplexer message send --to quality ...` from `community-base` | Exit 1: no `quality` tag has existed in this workspace | Durable messages use the sender's workspace namespace. |
| `APLEXER_WORKSPACE=/home/alexey/git/ai-shipping-labs aplexer message send --from community-base --to quality ...` | Exit 1: no `community-base` tag has existed in the AISL workspace | Setting the destination workspace does not preserve a verified cross-workspace sender identity. Do not impersonate an AISL sender to force it. |
| `aplexer send <release UUID> <text> --enter` | Exit 0 and text visible in the target's input box, but not submitted in the supplied screenshot | PTY write success is not agent receipt or action. `--enter` appends LF (`0a`), which produced a new input line in that Claude session. |
| `aplexer send <release UUID> --hex 0d --json` | Exit 0, one byte written; subsequent `aplexer status` changed from idle to working | CR (`0d`) appears to submit that pending Claude prompt. The user independently reported pressing Enter manually for a later message. There is still no machine-confirmed reply for our request. |

The source confirms the distinction. `src/bin/aplexer/session_commands.rs`
appends `b'\n'` for `send --enter`. `src/bin/aplexer/message_commands.rs`
appends `b'\r'` for `message send --pane`, and records pane traffic in the
mailbox only after a successful PTY injection. `src/bin/aplexer/cli_message_args.rs`
offers no cross-workspace destination for `message send` or `reply`.
`src/bin/aplexer/message_commands.rs` selects `APLEXER_WORKSPACE` or the
current directory, then resolves both sender and recipient within it.
`src/messaging/identity.rs` limits `--from` to a tag in that workspace.
`src/messaging/envelope.rs` records a single workspace in each message.
The existing design in `docs/inter-agent-messaging-design.md` explicitly
scopes durable messaging to one workspace and describes the PTY route as
at-most-once injection without confirmation of comprehension.

## Coordination protocol for this campaign

1. Name a person or session owner, repository, branch, worktree, base commit,
   file set, and issue for each task. Use a separate worktree for each change.
   The sender states whether it requests information, work, review, or action.
2. Before changing a file, check current ownership and obtain an explicit
   acceptance from the owner if the sets overlap. Treat a silent or idle
   session as unavailable. The human's relay above is accepted ownership
   evidence for the Home work, with the timestamp of this note.
3. Use `aplexer status <UUID> --json` or a filtered `aplexer list --json` to
   resolve a specific live target. Never use a bare tag from another
   workspace. Do not inspect or forward environment values or credentials.
4. Use native durable `aplexer message send --to <tag> <text>` for a sibling,
   adding `--workspace <destination>` for a peer in another workspace once
   the new version is installed. Send to the inbox first when the peer is
   busy. Add `--pane --or-inbox` only when the agent is idle at a known empty
   prompt and a timely
   nudge is appropriate. Include a request ID and ask for a reply repeating
   it. With the old installed CLI, send text and CR in separate writes with
   a short gap; a single text-plus-CR write left a Codex draft unsubmitted.
   For Codex text, an explicit bracketed paste before CR is more reliable;
   the candidate uses it, while raw byte modes stay raw.
   PTY input can interleave with the peer's work, so leave a busy peer's
   prompt alone.
5. Require a reply with that request ID before treating the message as
   received. CLI exit 0, changed activity state, or text in a capture is not
   an acknowledgment. If no reply comes, report uncertainty to the human or
   use the established repository handoff; do not repeat broad pings or
   reinterpret silence as consent. Process each message ID once even if it
   appears in both inbox and pane; reuse the first reply or outcome.
6. In each acceptance, record `owner`, `scope`, `branch`, `worktree`, `base
   SHA`, `expires/recheck`, and `next handoff`. For shared test resources,
   reserve concrete ports/databases and announce the reservation. At the time
   of this report ports 8030 and 8031 were reported busy, so allocate and
   verify another port before a local server run. AISL's current
   `_docs/PROCESS.md` requires separate test worktrees and its shared
   capacity coordinator for Playwright; it explicitly rejects a manual
   global serialization rule. Consult `_docs/testing-operations.md` for the
   actual reservation mechanism and worker budget.
7. Before a merge, recheck branch heads, owners and worktree status. Compute
   the merge with `git merge-tree --write-tree` and inspect the resulting
   relevant blobs as P18 requires. The owner of the target repository
   applies its own review/merge rules. Before any deploy, the designated
   release owner confirms version, environment, and authorization; other
   agents supply evidence and do not race that workflow.
8. Put handoff facts in a durable issue or repository evidence file with
   observation time and commit identity. Cross-workspace PTY text alone is
   transient and cannot be the only record of an ownership or deploy decision.
   Include push notice SHA and range so the next agent fetches the precise
   change before attempting a fix, avoiding duplicate or reverted work. Do
   not impose a new universal commit trailer: this repository prohibits
   attribution lines, and AISL has its own commit rules.
9. For SQLite data used in a test or rehearsal, use SQLite's backup API or
   the repository's documented fixture procedure, not a bare file copy from
   a live WAL database. For any content-bucket failure, name the run, commit,
   owner, and exact error before calling it baseline or attributable.
10. Production promotion remains with the AISL release owner and its process.
    Review the diff from the last deployed commit and promote an explicitly
    pinned tag after the development check. The single on-call engineer
    observes the latest pushed HEAD; other sessions do not launch competing
    CI watchers.

Suggested message body:

```text
[coordination id: AISL-CB-20260929-01]
From: community-base fc19aa35-48b6-4a62-b984-8adbf55fa6c5
To: AISL release 2ae31921-a52d-4863-b020-70e3d6a80d32
Intent: request ownership information only
Scope: parser/backend outside Home files in issue 1842 worktree
Please reply to my UUID with the same id, your reserved files/branch, and any conflict.
No merge, push, or deploy requested.
```

## Prioritized aplexer improvements

1. Fix `send --enter` submission across supported engines. The initial installed
   command appended LF while `message --pane` appended CR. The isolated aplexer
   worktree contains the reviewed fix using CR and a raw PTY test:
   before the fix the test observed `6162630a` for `abc` plus Enter and
   failed; after it, `6162630d` passed. A live pane send to a Codex peer
   then exposed a second defect: CR in the same PTY write left the framed
   text in the draft composer. The candidate now sends text and CR as
   separate RPC writes with a 300 ms editor turn between them, using a shared
   helper for `send --enter` and `message --pane`. Codex's source defines a
   120 ms paste-burst Enter suppression window. A focused raw PTY regression
   measures the gap and would fail at the former 100 ms delay. A final live
   pane send to an idle Claude peer submitted automatically and produced a
   matching reply. A later 300 ms pane probe to the active community-base
   Codex session remained in its input box, despite an empty prompt just
   before injection. An earlier probe needed manual Enter, as the user confirmed. Codex's
   explicit paste handler clears Enter suppression, so the candidate now
   brackets text submissions for Codex-family engines; hex, stdin, and raw
   pane modes retain their bytes. A disposable Codex session automatically
   submitted framed messages at idle and while working with the candidate.
   The installed bracketed-paste version subsequently passed one explicitly
   authorized test in the active human session, as recorded below. This
   does not imply an exactly-once or universal delivery guarantee.
2. Add native cross-workspace durable addressing with genuine sender session
   identity. The same candidate worktree implements `message send --workspace
   DEST --to TAG` and `message reply ID`, preserving the sender workspace and
   immutable session ID. It refuses cross-workspace `--from`. A test sent from
   workspace A to B, read B's inbox, replied from B, then read A's inbox with
   matching `reply_to`. Another test reused the sender's old tag and proved
   the new holder could not read the reply. An unresolved cross-workspace
   target is refused even with `--queue`. This is local same-host routing
   in the reviewed CLI, now installed locally as recorded below.
3. Add delivery state distinct from processing state: persisted, delivered
   to PTY, read, and application acknowledgment/reply. Expose request IDs,
   reply linkage, and a way to wait with a timeout. Same-workspace durable
   `message reply` already exists; the candidate extends its routing across
   workspaces. The candidate also adds `status: pty_written` to `send --json`
   and a message ID/source/reply command to pane frames. The candidate writes
   a durable inbox entry before pane injection, then marks successful pane
   delivery. A failed strict pane write exits nonzero with the stored ID and
   Inbox state; `--or-inbox` returns success with the replyable Inbox outcome.
   Focused tests cover both. During delivery, a recipient can see the same
   ID in the inbox and pane, so processing is not exactly-once. A
   process-level acknowledgment
   workflow remains future work. Do not label PTY-write success as a
   recipient acknowledgment.
4. Add a durable wake/notification path for an addressed agent. Current
   inboxes require polling at natural checkpoints; event-stream push and
   deferred pane delivery are still design-only in the messaging design doc.
   A wake must reconcile with the persisted inbox after restart.
5. Provide a coordination envelope or optional conventions for owner, files,
   worktree, branch, base SHA, resource reservations, and expiry. Aplexer can
   carry the data; repository process remains the authority for actual
   ownership, review, merge, and deployment.

## Peer input and limits

The release session was asked to co-design this protocol and describe its
coordination needs. A terminal screenshot and human relay establish that the
initial PTY message was visible but had not been submitted. A CR was then
sent and the session reported working. The user subsequently relayed detailed
feedback from the AISL peer after manually pressing Enter: it requested
session/branch/worktree/file-glob/time/resource ownership leases, capacity
holder information, precise push SHA/range notices, no shared-main edits or
dirty-tree stashes, safe SQLite backups, error attribution, and pinned-tag
promotion with a single on-call observer. The protocol above folds these in
where they agree with the current AISL process. Its suggested global
Playwright serialization and unconditional attribution trailer were not
adopted because the current process explicitly supersedes the former and
this repository's conventions forbid the latter. The peer also cited a
dirty-main stash/merge conflict that left markers in `urls.py` and crashed
the dev environment; that report is a reason to enforce the clean-main
gate, not independent verification of the incident here. An aplexer reply
with a matching request ID for the earlier peer discussion was not received
through aplexer. The detailed peer input above was relayed by the user.

The candidate binary at
`/home/alexey/git/aplexer-worktrees/send-enter-coordination-20260929/target/debug/aplexer`
sent inbox message `01a0eaeb-e9cb-72d3-9f76-bcea41779d7e` to AISL `quality`.
It recorded the community-base sender UUID and workspace. An early pane test
to `quality`, `01a0eaee-5d11-7fb3-b92f-9dcb451a9c70`, was visibly drafted
but required a separate CR to submit. After the shared delayed-Enter fix, a
single pane send to AISL `release` at an observed idle, empty prompt returned
`delivery: pane` with id `01a0eaf0-b627-7263-b190-3d0593ede424`.
The community-base inbox then contained reply
`01a0eaf0-c505-7392-88ad-ac9f2454f889` from `release`, with `reply_to`
equal to that pane message id and body `CB-R-20260929-01`. No manual Enter
was used for this final round trip. This proves one actual Claude peer
processed and replied to the native cross-workspace message. It does not
turn PTY-write success into general proof of processing; require a matching
reply for each consequential request. The root session independently read
the reply, confirmed its sender UUID and `reply_to`, then acknowledged only
that reply ID; the remaining inbox was left untouched. The sender identity
is resolved from local session records under a same-user trust model, without
cryptographic authentication.

For the Codex submit check, the active community-base root session's screen
showed an empty composer before the controlled pane message
`01a0eafd-9e53-7ea3-888e-08cbc6341c4b` was sent using the rebuilt 300 ms
candidate (SHA-256 prefix `3bb2c0fd`). Its screen then showed the message
still in the composer while the turn was marked Working; no extra Enter was
sent by the agent for that controlled probe. The user later submitted it
manually and explicitly reported doing so. The user had also confirmed manually submitting
the earlier probe `01a0eafb-da7c-7532-8737-8929b570840a`, which collided
with their own draft. The disposable Codex session
`554495c3-df06-4b48-8fcb-646b6dd82339` in
`/tmp/aplexer-codex-submit-probe-20260929` then processed a direct
`send --enter` nonce and an idle framed pane message
`01a0eafe-25ce-7c00-8faa-f9136490b665` automatically. A framed message
`01a0eaff-4bd7-7e52-a57d-8bcd196bf017` sent while that isolated Codex
agent was running `sleep 12` entered its pending-message queue and appeared
as a user message after the tool call. After the explicit bracketed-paste
change, isolated idle pane message `01a0eb00-202d-7e62-860e-f1e66d5975c6`
submitted automatically, and busy pane message
`01a0eb00-b1d3-7ea2-bba3-9fa6ca4f79d0` entered that pending-message queue.
These probes used only the owned scratch session. No further input was
injected into the human's draft. Aplexer's targeted PTY write status still
does not prove submission for an arbitrary recipient; the protocol requires
a reply or direct conversation evidence for consequential handoffs.

## Reviewed implementation and local installation

The implementation is committed as `2f09c02` on
`fix/send-enter-coordination-20260929` in
`/home/alexey/git/aplexer-worktrees/send-enter-coordination-20260929`.
It has not been merged or pushed. Independent review accepted the routing,
strict failure versus inbox fallback contract, documented duplicate-ID handling,
and final Codex paste handling.

- Four messaging integration tests passed: same-workspace reply/ack,
  cross-workspace routing with tag reuse and missing-recipient checks,
  strict pane failure, and opt-in inbox fallback.
- Raw PTY regression checks passed for CR, the separate submission delay,
  Codex paste framing and preservation of raw hex payloads.
- The pane framing unit and five transcript checks passed; the earlier
  library run passed 405 tests with two ignored.
- Formatting and diff checks passed. The skill validator passed.
- The reusable skill is committed locally in `../.agents` as `756922c`.
- The optimized CLI was built in a disposable installation worktree with
  the shared checkout's existing OpenCode builtin changes copied intact.
  A check confirmed the actual configured OpenCode launch was unchanged
  and its existing `--auto` builtin remained available with an empty config.
- Installation uses the repository's atomic installer; active workers are
  not restarted. The previous CLI is preserved at
  `/home/alexey/.local/bin/.aplexer-before-a2a-20260929`.

The source snapshot for the local build is
`/data/agents/aplexer/worktrees/a2a-install-20260929`; its two uncommitted
OpenCode files are copies of existing shared-checkout work, not part of this
change's commit. The final Codex paste fix was verified in an isolated idle
and working Codex session, and then in the active root session after the user
explicitly replied `go` and left the input untouched.

For that final live check, the root first captured an empty input box and
verified the installed binary SHA-256
`2c53a99efe0e1ede6e6ab737c239324ccad28edbb4991323dc256b53b9bd6465`.
One installed-CLI `message send --to community-base --pane` saved message
`01a0eb0e-ea6f-7fe2-b695-9f87fde3b001`, nonce `CB-CODEX-20260929-03`.
That exact message arrived as a conversation input automatically, without a
second Enter call or human submission. The root recorded receipt and
acknowledged the ID. This proves the installed fix submitted to the active
Codex session in this trial; the earlier manual submissions remain recorded
as failures of the preceding implementations.

The later quality handoff identified a tool process bound to a different
workspace from the displayed agent. Its cross-workspace reply was correctly
refused. The skill now checks `whoami` in the actual tool process before a
reply, without overriding sender identity. Our ownership ACK is saved in
the AISL quality inbox as `01a0eaf9-e475-73b3-9752-7fff41596e54` and names
the three issue-1842 files. Saving that ACK is not evidence that the peer
has read it.

For issue 1842, the existing AISL capacity coordinator admitted the engineer's
four-worker browser run after waiting for load headroom. The scoped Django
stage passed 5,377 tests with 10 skips, and core Playwright passed 993 tests.
This is evidence that the repository's coordinator works for this run; it is
not a reason to introduce a second global lock. The independent tester runs
after the engineer in the same issue worktree, and publishes the local log
path and stage transitions to the orchestrator.

## DTC integration handoff using the installed protocol

The first DTC #438 integration requests were durable inbox messages. No reply was assumed.
When the recipient was idle, a rendered pane capture established that its composer showed the
placeholder `Ask Codex to do anything`, rather than an unfinished draft. A single pane
notification, `01a0eb6d-4de3-7d73-9572-bbc3bdbca254`, asked the peer to read the existing handoff.
The peer became active and replied with explicit ownership information and release of the
integration slot. No additional Enter call or human intervention was requested.

The ownership ACK arrived under two IDs, `01a0eb70-13b4-7702-be02-1fc031186a9d` and
`01a0eb70-14c2-7a02-ac8a-eb927b76723f`, with the same request token and content. Both were
acknowledged, but the handoff was processed once. Distinct transport IDs do not authorize
repeating an action whose coordination token and outcome are already recorded.

The root announced the exact push range and used a separate clean integration clone. DTC
`origin/main` then advanced from `cfc21a90` to `f143a19`, containing only the approved #438
commit and its merge. Reply `01a0eb71-5cc6-7440-a2cc-ad0079a9bf67` recorded the resulting SHA
and sole CI observer. The peer's 14 unpushed coding-standard commits, unrelated template WIP,
and shared main checkout were untouched. This confirms a consequential cross-workspace
handoff using explicit agreement, in addition to the earlier transport probes.

## Follow-up: Codex launched inside a shell

The AISL quality pane exposed a remaining case: its session record says `shell`, although
the running application is Codex. Native framed message `01a0eb78-5d63-7451-8ba9-9cff18469e21`
remained in its composer with the first installed build. The root inspected the complete
unchanged coordination draft and submitted one CR. This is a failure of that native attempt,
not evidence of automatic submission. The peer then replied through its actual tool identity,
`dapier/ui`; no AISL ownership release was inferred from that relay.

Focused commit `50b76c3b05ce0246c71e0f758d2b37ffc32f0238` makes framed `message --pane`
submission honor the live terminal's advertised bracketed-paste mode. It retains the explicit
Codex fallback and preserves raw/hex and ordinary shell-send contracts. Root review accepted
the five-file change. Verification passed 193 binary tests, four messaging tests, and 27 screen
tests with one ignored, plus formatting and diff checks.

The optimized binary was built from the existing installation snapshot plus this exact patch,
preserving its unrelated OpenCode configuration/test overlay. The OpenCode builtin test and
the shell-pane test passed in that snapshot. Atomic installation did not restart active workers.
The installed binary hash is
`25027cb5511496cea3818bf9a486aa286554f74d437c671b9aeebcd1134d3f42`;
the prior binary is preserved at `/home/alexey/.local/bin/aplexer.pre-shell-fix-20260929.bak`.

An owned shell-launched Codex session using the installed binary automatically submitted
message `01a0eb87-0713-78b0-b9d5-e59821d4ab37`, visibly replied
`SHELL-CODEX-INSTALLED-20260929-01`, and returned to an empty composer. No manual Enter or
peer/human probe was used. The owned scratch session was removed afterward. This verifies
the observed shell-hosted case; terminal paste support still does not establish composer
readiness, and a successful pane write still requires an acknowledgement for consequential work.

## Installation drift during later coordination

During the #324 package handoff, the installed CLI reported version `0.1.8` and rejected
`message send --workspace`. Its hash had changed to
`8aec59c7894e0efe112337769df61bf14685dd21e51079dcfa6623f415ef318a`.
The preceding installation/probe results remain historical evidence, not a claim that the
current default binary retains the reviewed transport features.

The existing isolated worktree's `target/debug/aplexer` still advertises native cross-workspace
send/reply and resolves this session's real identity. Its hash is
`d648c2fc10ad6aac8f69b41a0df33d7a0f8c2bb4a568c265f7a5648d4900bb3b`.
Using that explicit path recorded AISL ownership notice `01a0ed97-806f-75d3-bee6-d2869fea1503`
and integration request `01a0ed97-80e9-7350-8029-f3165447ab8b` to the active aplexer
`commits` session. Each names the exact binary path needed for cross-workspace replies.
Neither receipt proves the recipient has processed it. No active composer or shared binary
was modified. Integrating the focused source commits into the maintained aplexer branch remains
necessary so a later install preserves the feature.

The former DTC `conding-standard` session also disappeared from session discovery. Its #440
pre-push notice failed rather than reaching an assumed successor. The resulting SHA and sole
on-call handoff were recorded in the DTC issue; no peer acknowledgement was invented.

### Maintainer acknowledgement and integration review

The two focused source commits are published in draft
[PR #23](https://github.com/PocketShell-io/aplexer/pull/23). A single pane wake-up,
`01a0edab-71bc-7992-b030-06f42d5b3525`, was sent after checking an idle session and empty composer.
The maintainer replied in durable message `01a0edb0-6e13-7761-8a35-df45af44c3ca`, explicitly
acknowledging `APLEXER-A2A-PRESERVE-20260929` and reserving the mouse/scroll/README changes.
Root acknowledged that reply as `01a0edb1-1175-7741-93c1-bc0731c12eae`.

The agreed next step is isolated conflict resolution: preserve main's live session-record
workspace lookup when moving routing into `message_routing.rs`, then send the updated SHA and
test evidence to the maintainer for combined-tree review. The shared checkout and installed
binary remain untouched. This is an agreed handoff, not evidence of completed integration.

The isolated rebase is now published at `d6b279a3f8b613f376798058ca771afd28f3d54c`, on
main `2254b2ee5e084e361515a4ab1a9a841885223794`. The first focused commit preserves the live
record lookup and the full inbox/log/show/ack/gc dispatcher; the second preserves shell-hosted
Codex submission. The tested final tree is `b80dd7de493c87ecee3e10ebf11f14fe30280c2c`.
Formatting, 195 binary tests, six messaging tests and 27 screen tests passed; one screen test
was ignored. No shared installation changed.

Hosted CI passed MSRV compile but failed Validate before tests on a `collapsible_if` warning
in the maintainer's reserved `scroll_input.rs:179`. The
[CI report](https://github.com/PocketShell-io/aplexer/pull/23#issuecomment-5893105917)
records that unresolved gate. The new review wake-up `01a0edbc-9a0d-70f0-87b3-315b4842004e`
automatically entered the peer conversation; a rendered capture showed the maintainer reading
the two named inbox messages and inspecting the reserved source. No manual Enter was used.
Combined-tree review, CI correction and maintained installation remain pending.


### Worker retirement race discovered by CI

The maintainer released the exact Clippy guard correction. Commit
`e18fda68fd78bb33ae158b1936b2b67420daf394` contains that focused correction; hosted MSRV
passed, but Validate then failed the worker self-reap integration test. An isolated reproduction
showed a history checkpoint recreating deleted session state after an idle-timer reset. Relevant
worker and persistence source matches the main baseline; this was not reproduced through the
message/send path. The separate baseline binary was not executed.

[Issue #24](https://github.com/PocketShell-io/aplexer/issues/24) tracks the race. The maintainer
released the worker/persistence paths for an isolated fix. Local commit
`10dac68d03770fd6f97d957707573d9c643dcf93` atomically requires an existing record when
publishing running-worker state and prevents later history writes from recreating a removed
session directory. Deterministic deletion-during-publication and checkpoint regressions passed,
as did the focused self-reap, persistence and lifecycle tests. The candidate is not pushed.

The maintainer identified a remaining startup requirement: test the atomic exchange operation
on the actual session record before launching any workload, so an unsupported filesystem fails
before a child exists. This follow-up and a deterministic failure-before-spawn regression are
assigned in the same isolated worktree. Maintainer message
`01a0eddc-0238-7d32-aad8-ed96f46a6c4e` and root acknowledgement
`01a0ede1-9276-7ee0-bed9-061832af144f` record the handoff. CI, combined-tree acceptance and
maintained installation remain open. No timeout weakening or ordinary-rename fallback is allowed.


The maintainer accepted the prelaunch check in local commit `145885c2` and requested an explicit
filesystem diagnostic and README note. Focused follow-up `ca53b4ab762e5d7683ebbbd896cb126fceb4b648`
adds those; the PR branch was fast-forwarded without changing main or installing a binary.
Its tree is `c27b4874c4b1507935b9bf2bb57e6c445a201d9f`.

[Hosted CI](https://github.com/PocketShell-io/aplexer/pull/23#issuecomment-5894001380)
passed exact run `36594661581`: formatting/Clippy, 786 default Rust tests, 19 startup-hook tests,
36 Python tests and 20 Python CLI tests plus five subtests. The original worker self-reap test
and unsupported-exchange prelaunch regression passed. Rust 1.85 all-target compilation passed.
The maintainer received the integration handoff as automatically submitted pane message
`01a0edec-c251-7670-b818-2f001fbd4fc5`. Combined integration and maintained installation remain
pending; active workers and the preserved communication binary were not restarted or replaced.


The maintainer then supplied clean combined branch `fix/mouse-a2a-integration-20260929` at
`6a71a69f850a42956ba4bf434b5f7e4599d260e9`, tree
`46a2c25795ca88fc0c50aa9ad4e926bd70073efa`, directly on top of the green messaging/lifecycle
candidate. Its six mouse/README paths passed local formatting, Clippy, 197 binary tests,
six messaging tests and 27 screen tests with one manual case ignored. The maintainer released
those files for PR integration in message `01a0edf9-5868-7491-9a62-550e4d1dbfc9`.

Root fast-forwarded PR #23 to that exact commit; sole hosted observer reported run `36598114529`
[green on attempt 1](https://github.com/PocketShell-io/aplexer/pull/23#issuecomment-5894458020):
788 Rust tests passed with six existing ignored, 19 startup-hook tests, 36 Python client tests,
and 20 CLI tests plus five subtests. Formatting, Clippy and Rust 1.85 compilation passed.
No main merge or installation occurred. The maintainer explicitly owns installation because the
current binary also contains separate uncommitted `src/config/{pathfix.rs,schema.rs}` behavior.
Installing a build of the PR alone would drop that behavior. Shared main WIP and active workers
remain untouched. Root acknowledgement and exact push/observer handoff are durable messages
`01a0ee00-04a9-7260-9d1e-45e68a5fb878` and `01a0ee00-7855-73c0-9260-be792a0bdfc1`.


The final main merge preview against freshly fetched `2254b2ee5e084e361515a4ab1a9a841885223794`
is conflict-free and exactly the tested tree `46a2c25795ca88fc0c50aa9ad4e926bd70073efa`.
Root sent final source acceptance/integration request `01a0ee07-5865-7b50-b1ba-515e2bbf6bcb`;
the maintainer's explicit main-merge hold and installation ownership still apply pending its reply.
