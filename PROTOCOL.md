---
protocol: agent-coordination
version: 1.0.0
---

# Agent coordination protocol

Two independent agent sessions — different harnesses, no shared process — work on one
repository: one implements, one reviews. They exchange work through a mailbox on the
shared filesystem instead of through a human copying text between applications.

This file is the single authority. Harness skills are thin shims over it. The design
reasoning, and the evidence behind each rule, is in
`docs/2026-09-15-agent-coordination-protocol-design.md`.

## Vocabulary

| Term | Meaning |
|---|---|
| **run** | One coordinated effort, `<date>-<topic>`. Has one mailbox. |
| **role** | `implementer` or `reviewer`. Assigned by the human, never inferred. |
| **checkpoint** | A review boundary defined by the run's plan, not by this protocol. |
| **snapshot** | A commit object naming the exact revision a review evaluated. |
| **handoff** | A message presenting a snapshot for review. |

## Roles and authority

**The implementer** is the sole writer of implementation files, the real git index,
and branch references. It mints snapshots. It pauses work at a handoff, and during
snapshot capture.

**The reviewer** writes mailbox messages and its own journal. It must not modify
implementation files, the real index, or any git reference. Its drift checks write
nothing at all.

**Verification is never assumed pure.** The handshake carries a table of verification
commands, each marked `source` (rewrites files under review — forbidden to the
reviewer), `artifacts` (touches allow-listed caches and build metadata only), or
`none`. Check each command; do not infer from its name. A worked example: `pnpm lint`
in some repositories is `biome check --write --unsafe`, which rewrites the code under
review.

**The human's authority is absolute and immediate.** A conversational answer is
authoritative the moment it is given. This protocol is a delivery mechanism, not a
source of authority over the human's instructions.

## Starting a run

1. The human assigns roles explicitly.
2. The initiator initialises the mailbox and publishes a `handshake`.
3. The counterpart replies `handshake-ack` with `accepted` or `amended`.
4. **An amended ack must itself be accepted**, so both sides start from one final
   handshake revision.
5. No work begins without a mutual acceptance.

```sh
coord-check --mailbox "$MAILBOX" --role "$ROLE" --init
shasum -a 256 "$PROTOCOL_DIR/PROTOCOL.md"     # pin this digest in the handshake
```

The handshake declares, and each participant declares **only its own** capabilities:

```yaml
protocol: { version: 1.0.0, digest: <sha256 of this file> }
run: <run-id>
mailbox: <absolute path>
repo: <absolute path>
branch: <branch>
base: <commit the work starts from>
plan: <path>                      # supplied at invocation, never hardcoded
spec: <path>
participants:
  implementer: { agent: …, harness: …, wait: { mode: active-wait, max_seconds: 600 } }
  reviewer:    { agent: …, harness: …, wait: { mode: active-wait, max_seconds: 60 } }
checkpoints:   [ { id: 1, after: <task>, scope: [<pathspec>…], review: <text> } ]
verification:  [ { cmd: …, mutates: source|artifacts|none } ]
artifacts_allowlist: [ … ]
ignored_inputs: [ … ]             # gitignored paths that are real verification inputs
retention: keep-refs|bundle|discard
pause_policy: <when implementation stops>
```

A later digest mismatch halts the run for re-acceptance: editing this file mid-run
must not silently change the rules a run is operating under.

## Wake mechanisms

Each side declares one: `active-wait` (keeps its turn open while a tool waits),
`scheduled-resume` (a scheduler opens a later turn), or `manual` (the human nudges).
The wait bound is per side — a universal bound would conflict with a harness whose own
instructions cap blocking waits.

Waiting is a bounded loop **inside a single tool call**, not one model turn per check.
**A timeout changes waiting state and nothing else.** It never releases dependent work,
never implies approval, never advances a checkpoint.

## The review cycle

```
handoff(snapshot S) → review(reply_to, snapshot S, outcome)
   ├─ approved          → dependent work released, for S only
   ├─ changes-requested → fix → revision(snapshot S′) → review …
   ├─ needs-user-input  → escalate
   └─ blocked           → escalate
```

An approval **names the snapshot it approves**. Acknowledgement is not approval.
Silence is not approval. A timeout is not approval. Approvals never carry across
revisions.

Before resuming dependent work, re-verify that the working tree still matches the
approved snapshot. If it has drifted, the approval no longer applies.

### Publishing a handoff

```sh
coord-snapshot --repo "$REPO" --run "$RUN" --message-id "$MSG" \
               --base "$BASE" --scope $SCOPE
# → base, head, snapshot, patch_manifest, env_manifest, excluded, stable

coord-publish --mailbox "$MAILBOX" --from implementer --to reviewer --type handoff \
              --checkpoint N --base "$BASE" --snapshot "$SNAP" \
              --patch-manifest "$PM" --env-manifest "$EM" --scope $SCOPE \
              --body handoff.md
```

The body is whatever handoff template the run's plan defines. This protocol carries
the envelope; it does not impose a second body format. Whatever the template, supply
every item it asks for — "not run" is an acceptable answer, silence is not.

### Reviewing

```sh
coord-check  --mailbox "$MAILBOX" --role reviewer --json
coord-verify --repo "$REPO" --base "$BASE" --snapshot "$SNAP" --scope $SCOPE \
             --patch-manifest "$PM" --env-manifest "$EM" --head "$HEAD"
# … run only non-mutating verification …
coord-verify … again
coord-publish --mailbox "$MAILBOX" --from reviewer --to implementer --type review \
              --reply-to "$HANDOFF" --outcome approved --body review.md
coord-check --mailbox "$MAILBOX" --role reviewer --record "$HANDOFF" \
            --action reviewed --response "$REVIEW"
```

`coord-verify` binds to the snapshot itself: it checks the snapshot exists, that its
scoped manifest equals the declared `patch_manifest`, and that its parent is the
declared base. Comparing the working tree against a digest alone proves none of that —
an all-zero snapshot id would otherwise "verify".

`ignored_inputs` are declared once in the handshake and both sides pass the same set.
An asymmetric declaration makes the environment fingerprints differ for a reason that
has nothing to do with the code.

`coord-verify` runs **before and after** verification. Either drift invalidates the
result: patch drift means the reviewed change moved; environment drift means something
outside the scope moved that could affect the outcome. Report drift as drift — never
as a pass.

## Messages

`messages/<UTC-timestamp>-<role>-<type>-<random>.md`. The random suffix is required:
one role can publish two messages of the same type within one second.

**Filename order is display only. Causality comes from `reply_to` and protocol
state** — a late publication can land behind an existing cursor.

Messages are **immutable**. Publication is a hard link, which refuses an existing
destination; `mv` would silently clobber. A correction is a new message carrying
`supersedes:`.

Types: `handshake`, `handshake-ack`, `handoff`, `review`, `revision`, `question`,
`decision`, `status`, `end`. Outcomes (reviews only): `approved`,
`changes-requested`, `needs-user-input`, `blocked`.

### The mailbox is not content

The mailbox lives inside the repository, so `coord-snapshot` and `coord-verify`
exclude `.coord/` from the environment fingerprint. Without that, publishing a handoff
writes into the mailbox, the mailbox lands in the fingerprint, and **the act of handing
off invalidates the review it carries**. Pass `--exclude <path>` to extend the
exclusion; `.coord` is always excluded.

## Crash recovery

`coord-check` reconciles before reporting. Two windows:

- **Acted, not recorded** — a journal entry with no published response. The action was
  interrupted: **inspect its actual state and report it.** Do not repeat it blindly.
  It is reported as `interrupted`, never re-served as fresh work.
- **Published, not journalled** — the response reached the mailbox and the session
  died. `coord-check` discovers it by author and `reply_to`, and reconciles the
  journal, so no duplicate response is published and no implementation work is redone.

**Intermediate replies do not complete their parent.** Only `review`, `revision`,
`handshake-ack`, `decision` and `end` conclude the work their parent asked for. A
`question` or `status` leaves the parent unresolved — otherwise asking for
clarification would silently close the review it was about.

Journal writes are atomic replacement. Delivery is at-least-once with reconciliation.
Exactly-once execution is not claimed, and calling actions idempotent would not make
it so.

## Escalation

A `question` escalates. Both agents **pause dependent work while keeping their declared
monitoring mechanism alive** — an agent that simply stops may never learn the answer.

The human answers in whichever session is convenient.

- The receiving agent records it as a `decision`, preserving its meaning, linked by
  `reply_to`, naming the checkpoint that resumes.
- **Coordinated** dependent work waits until publication succeeds.
- If publication fails, **report the failure**. Never ask the human to repeat an answer
  already given.
- Stop and cancellation take effect immediately, whether or not recording succeeds.

## Visibility

The human must be able to follow the run without opening files. Print a short
**user-facing** block — in reply text, not stdout buried in tool output — on exactly
five events: publishing a handoff, receiving findings, requesting a decision,
completing a checkpoint, escalating.

```
Checkpoint 1 · snapshot 622817e · changes-requested
Next: addressing 3 findings, then revision handoff
.coord/<run>/messages/<id>.md
```

Empty polls print nothing. A timed-out wait prints one line, and only when stopping.

## Ending a run

```sh
coord-end --repo "$REPO" --run "$RUN" --retention keep-refs
coord-end --repo "$REPO" --run "$RUN" --retention bundle --archive run.bundle
```

Cleanup follows the declared policy. Under `discard`, archived transcripts are no
longer independently reviewable — the tool says so out loud.

## Helpers

| Helper | Role | Writes |
|---|---|---|
| `coord-manifest` | both | nothing |
| `coord-snapshot` | implementer | git objects + `refs/coord/<run>/<msg>` |
| `coord-verify` | reviewer | nothing |
| `coord-publish` | both | one message (hard link, never replaces) |
| `coord-check` | both | that role's journal (atomic replacement) |
| `coord-end` | implementer | per the retention policy |

`tests/run` exercises all six. The fixtures are the cases that broke earlier designs:
a filename containing a newline, a symlink target ending in a newline, a mode/name
ordering conflict, a deleted-but-cached tracked file, an unreadable file, and both
crash windows.

## Unsupported, and refused rather than mishandled

`.gitattributes` declaring `filter`, `text` or `eol`; submodules; unreadable files.
Read-only helpers run with `GIT_OPTIONAL_LOCKS=0` so git cannot refresh the index's
stat cache underneath a reviewer who is forbidden to write it.
In those repositories the helpers exit non-zero rather than produce a manifest that
cannot be compared.
