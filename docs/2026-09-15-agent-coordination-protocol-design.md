# Agent coordination protocol — design

**Status:** design, awaiting review. Nothing is built yet.
**Date:** 2026-09-15
**Canonical home:** `/Users/tony/Clients/Infonomic/Projects/agent-coordination/`

## The problem

Two independent agent sessions — different harnesses, different vendors, no shared
process — work on one repository: one implements, one reviews. Today every review
milestone is copied by hand from one application into the other. That is slow, it
loses fidelity, and it makes the human the transport layer for work the agents could
exchange directly.

Both sessions already share a filesystem and a checkout. That is enough to carry a
protocol. No server, no MCP, no network.

## What this is not

- Not an orchestration framework. It coordinates two named participants on one run.
- Not a scheduler. Waiting is whatever each harness already provides.
- Not project-specific. Plan paths, specification paths, checkpoint definitions,
  review scope, and verification commands are **inputs supplied at invocation**, never
  values baked into the protocol.
- Not a permanent feature of any project it is used on. A project acquires a
  temporary, locally ignored mailbox and nothing else.

## Locations

| Purpose | Location |
|---|---|
| Canonical design, protocol, helpers, harness shims | `/Users/tony/Clients/Infonomic/Projects/agent-coordination/` |
| Claude personal entry point | `/Users/tony/.claude/skills/coordinate/` |
| Codex personal entry point | `/Users/tony/.agents/skills/coordinate/` |
| Temporary project runtime | `<project>/.coord/<run-id>/` |

Both harness shims are versioned in the canonical repository. Personal installations
resolve to those maintained copies rather than holding independent ones — one
protocol, two thin shims, no drift. Do not install duplicate copies into both
`~/.agents/skills/` and `~/.codex/skills/`.

The project mailbox is ignored through `<project>/.git/info/exclude`, which is local
and uncommitted, so even the ignore rule leaves no trace in the project's history.

## Roles and authority

Roles are **assigned by the human at invocation** — never inferred from which
application opened first, and never negotiated between the agents.

**The implementer** is the sole writer of implementation files, the real git index,
branch references, and snapshot references. It creates review snapshots. It pauses
work at a handoff.

**The reviewer** writes mailbox messages and its own coordination state. It must not
modify implementation files, the real index, or any git reference. Its drift checks
write nothing at all — not even git objects.

**Verification is not assumed pure.** The handshake carries an explicit table of
verification commands, each marked mutating or non-mutating, and each checked rather
than inferred from its name. A separate allow-list names the artifact paths a
verification run may touch (caches, build metadata, coverage). Anything outside the
allow-list is a violation.

> Worked example, from the trial project: `pnpm lint` is `biome check --write
> --unsafe --diagnostic-level=error` in every package. A reviewer running it in a
> shared checkout rewrites the code under review, with unsafe fixes. Its read-only
> form is `biome check`. This belongs in the run's verification table — not in the
> protocol.

## Run lifecycle

A **run** is one coordinated effort: `<date>-<topic>`, for example
`2026-09-15-relation-create-part1`.

```
start/join → handshake → accepted → work → snapshot → handoff
                                              ↓
                                           review ──→ approved      → next checkpoint
                                              ├────→ changes-requested → revision → review
                                              ├────→ needs-user-input  → escalate → decision → resume
                                              └────→ blocked           → escalate
```

### Handshake

The initiator publishes a `handshake` proposing the run. The counterpart replies
`handshake-ack` with `accepted` or `amended`. **An amended acknowledgement must
itself be accepted** by the original proposer, so both agents demonstrably start from
one final handshake revision. No work begins without a mutual acceptance.

The accepted handshake pins the **protocol version and a digest of `PROTOCOL.md`**,
so editing the canonical protocol mid-run cannot silently change the rules a run is
operating under. A digest mismatch at any later action halts the run for
re-acceptance.

Each participant declares **its own** capabilities. The initiator may propose
identities; it must not assert the counterpart's available wake mechanism or wait
bound.

```yaml
protocol:
  version: <semver of PROTOCOL.md>
  digest: <sha256 of PROTOCOL.md at acceptance>

run: 2026-09-15-relation-create-part1
mailbox: /abs/path/to/project/.coord/2026-09-15-relation-create-part1
repo: /abs/path/to/project
branch: refactor/forms
base: <commit sha the work starts from>
plan: specs/2026-09-14-embedded-relation-creation-plan.md
spec: specs/2026-09-14-embedded-relation-creation-spec.md

participants:
  implementer:
    agent: claude-opus-5
    harness: claude-code
    wait: { mode: active-wait, max_seconds: 600 }
  reviewer:
    agent: gpt-6-astra
    harness: codex
    wait: { mode: active-wait, max_seconds: 60 }

checkpoints:
  - id: 1
    after: Task 1
    scope: [packages/admin/src/forms]
    review: <scope text lifted from the plan>

verification:
  - { cmd: "pnpm lint",      mutates: source }
  - { cmd: "biome check",    mutates: none }
  - { cmd: "pnpm typecheck", mutates: artifacts }
  - { cmd: "pnpm knip",      mutates: none }

# mutates: source     — rewrites files under review; forbidden to the reviewer
#          artifacts  — touches allow-listed caches/build metadata only
#          none       — writes nothing

artifacts_allowlist: ["node_modules/.cache", ".turbo", "**/*.tsbuildinfo", "coverage"]
ignored_inputs: [".env", ".env.local"]     # gitignored, but real verification inputs
retention: keep-refs                        # keep-refs | bundle | discard
pause_policy: implementation pauses from snapshot creation until the review lands
```

### Wake mechanisms

Each side declares one of `active-wait` (keeps its turn open while a tool waits),
`scheduled-resume` (a scheduler opens a later turn to check), or `manual` (the human
nudges it). The wait bound is **per side** — a universal bound would conflict with a
harness whose own instructions cap blocking waits.

For `active-wait`, waiting is a bounded loop inside a single tool call, not one
model turn per filesystem check. **A timeout changes the waiting state and nothing else.** It never
releases dependent work, never implies approval, and never advances a checkpoint.

## Mailbox mechanics

```
<project>/.coord/<run-id>/
  messages/    immutable published messages
  tmp/         staging; never read by the counterpart
  state/       per-role cursor and journal
```

### Message identity

`<UTC-timestamp>-<role>-<type>-<random>.md`

The random suffix is required, not decorative: one role can publish two messages of
the same type within one second, and higher-resolution timestamps alone do not fix
it. Verified — three ids generated in the same second were identical until the suffix
was added.

Filename order is for **display only**. Causality comes from `reply_to` and protocol
state. A late publication can land behind an existing cursor, so ordering must never
be inferred from names.

### Publication

Write to `tmp/<id>.md`, then `ln tmp/<id>.md messages/<id>.md && rm tmp/<id>.md`.

A hard link **refuses** to replace an existing destination; `mv` silently clobbers it.
Verified: `mv` overwrote a published message without complaint, `ln` failed with
`File exists` and left the original intact. Publication is therefore a link, not a
rename.

Published messages are **immutable**. A correction is a new message carrying
`supersedes:`.

### Envelope

```yaml
id: 20260915T064210Z-implementer-handoff-a21d5fa58f97
run: <run-id>
from: implementer
to: reviewer
type: handoff          # handshake handshake-ack handoff review revision
                       # question decision status end
at: 2026-09-15T06:42:10Z
reply_to: <id or null>
supersedes: <id or null>
checkpoint: 1
base: <sha>
snapshot: <sha>
patch_manifest: <sha256>
env_manifest: <sha256>
scope: [packages/admin/src/forms]
outcome: <review messages only>
```

`outcome` is one of `approved`, `changes-requested`, `needs-user-input`, `blocked`.

The **body** of a handoff is whatever handoff template the run's plan already
defines. The protocol carries the envelope; it does not impose a second body format.

## Review snapshots outside branch history

A review must name the exact revision it evaluated. "Checkpoint 1 approved" is
ambiguous the moment anything else is edited.

This creates a commit object and a reference to it. It leaves the branch, `HEAD`, and
the real index unchanged — but it **does** write git metadata. Authorization to mint
review snapshots is therefore distinct from, and does not imply, authorization to
commit implementation changes onto the branch.

```sh
TMPIDX=$(mktemp)
GIT_INDEX_FILE=$TMPIDX git read-tree  "$BASE"          # seed from the agreed base
GIT_INDEX_FILE=$TMPIDX git add -A --  $SCOPE           # capture the agreed scope only
TREE=$(GIT_INDEX_FILE=$TMPIDX git write-tree)
SNAP=$(git commit-tree "$TREE" -p "$BASE" -m "coord snapshot <run> <checkpoint>")
git update-ref "refs/coord/$RUN/$MSG_ID" "$SNAP"
rm -f "$TMPIDX"
```

Verified behaviour: the scoped capture included a modified tracked file **and** a new
untracked file, excluded a gitignored file, and excluded an unrelated edit outside
the scope. `HEAD`, the branch, and the real index were untouched — `git status` was
identical before and after. The reference survived `git gc --prune=now`.

Requirements this imposes:

- **Scope is explicit.** A repository-wide `git add -A` would capture unrelated user
  edits. Gitignored files are excluded; "untracked files are included" means
  untracked-and-not-ignored.
- **Implementation pauses during capture**, not only during review. Capturing files
  is not an atomic read of the checkout.
- **The handoff records** base SHA, snapshot SHA, the included scope, and any
  excluded changes.
- **Retention is declared, not assumed.** Promoting a transcript full of SHAs does
  **not** keep the objects alive: once the run's references are deleted, garbage
  collection can remove the snapshots and the transcript becomes a list of identifiers
  nobody can review. The handshake declares one policy and `coord-end` follows it —
  `keep-refs` (references retained, snapshots stay reviewable in the checkout),
  `bundle` (`git bundle create` archives the snapshots into the coordination records
  before references are deleted), or `discard` (references deleted, and the archived
  transcript explicitly documented as no longer independently reviewable).

## Drift detection

An immutable snapshot stabilises the diff. It does not make verification run against
that snapshot — verification runs against the working tree. So the reviewer checks two
fingerprints, before **and** after verification.

**Patch drift** — has the reviewed change itself moved?
**Environment drift** — has anything outside the scope moved that could affect
verification? A dependency, a configuration file, a test helper.

### One serializer, two sources

`git ls-tree` output and a shell loop over the working tree are **not**
interchangeable, and trying to make them equal produced three defects: different
scope (the tree listing covered the whole snapshot, the loop only the scope),
different ordering (`sort` over generated records orders by mode then object id;
`ls-tree` orders by name), and different path encoding (`ls-tree` quotes unusual
filenames; the loop emitted raw bytes into a newline-delimited stream, so a filename
containing a newline broke equivalence).

Both sources therefore feed **one canonical serializer**, `coord-manifest`, which
reads either a git tree or the working tree and emits the same bytes. Shell is the
wrong tool for byte-exact work; the helper is Python.

```
record:  <mode> SP <oid> HT <path> NUL        ordered by path bytes
absent:  <ABSENT> HT <path> NUL               declared input that does not exist
```

- **Scope is identical on both sides** — the same pathspec is passed to `git ls-tree
  -r -z` and to `git ls-files -z`.
- **Ordering is by path bytes**, never by record content.
- **NUL-delimited throughout**, with raw unquoted paths, so a filename containing a
  newline cannot corrupt the stream.
- **Object ids are computed, not shelled out** — `sha1("blob <len>\0" + bytes)`, with
  the repository's object format read from `git rev-parse --show-object-format` so a
  sha256 repository is handled rather than silently mis-hashed.

The format carries what a per-file content digest misses: **mode** distinguishes
`100644` from `100755`, and **`120000`** marks a symlink whose object is its target
string, so repointing a link between two identical-content files changes the manifest.
Both were live false negatives in the first draft of this design.

### Symlink targets are preserved, not trimmed

The rule is *preserve the target bytes*, not *strip trailing newlines*. Shell command
substitution strips **all** trailing newlines, including legitimate ones in a target.
`os.readlink` returns the exact bytes and is what the helper uses.

This is not hypothetical: while building the test fixture, `ln -s "$(printf 'targ\n')"`
silently created a link to `targ`, because the shell ate the newline before `ln` ever
saw it. The tree recorded four bytes, not five.

### Deletions and failures are defined, not incidental

`git ls-files --cached` still lists deleted tracked files. A naive loop tries to hash
them, writes a malformed record to stderr, and **exits zero** — a corrupt manifest
reported as success.

- An **intentional deletion** produces an absent entry, mirroring its absence from the
  snapshot. If the snapshot still has the file, the manifests differ and drift is
  correctly reported.
- An **unexpected read, stat or hash failure aborts** the whole manifest with a
  non-zero exit and a named path. Nothing is emitted.
- A **declared ignored input that is missing** gets an explicit `<ABSENT>` record, so
  its later creation changes the manifest. Verified stable across repeated runs and
  detected on creation.
- Failure is never inferred from a pipeline's final exit status.

Unsupported configurations are refused up front rather than mis-hashed:
`.gitattributes` declaring `filter`, `text` or `eol` (working-tree bytes then
legitimately differ from the stored blob), submodules, and unreadable files.

### The patch manifest is derived from the snapshot, not computed beside it

The patch manifest is `coord-manifest --source tree --rev <snapshot>` — a pure
function of the snapshot's contents. A manifest computed separately from the working
tree could describe different bytes than the snapshot it sits next to, and a later
check could approve snapshot A on verification performed against contents B. Deriving
it from the tree makes that mismatch impossible rather than unlikely.

The reviewer runs `coord-manifest --source worktree` over the same scope. Verified:
identical digests across a filename containing a newline, a symlink target ending in a
newline, a mode/name ordering conflict, and a deleted-but-cached tracked file — the
same fixtures on which the earlier shell algorithm produced two different digests. The
helper writes nothing: no git objects, no index, no references.

### Capture stability

The snapshot helper computes the working-tree manifest, mints the snapshot, derives
the snapshot manifest, and recomputes the working-tree manifest. **All three must be
equal** — comparing only the two working-tree manifests would not prove either matches
what the snapshot actually stored. If they differ the checkout moved mid-capture:
retry, and fail after a bounded number of attempts rather than record a torn
snapshot.

### Environment fingerprint

The same entry format applied to changed paths **outside** the scope, plus the agreed
`HEAD` object id. Carrying `HEAD` detects a checkout change — a rebase, a branch
switch, a merge — even when the visible file bytes are identical.

`--exclude-standard` omits ignored files, and some ignored files are genuine
verification inputs: local configuration, `.env`. The handshake therefore names
`ignored_inputs:` explicitly and those are included in the fingerprint. What stays
outside coverage is stated rather than implied — anything ignored and not declared,
anything outside the repository, and installed dependency trees.

Two earlier findings still stand behind this design, both verified:

- `git status --porcelain` is **not** a content fingerprint. Across a real content
  change to an already-modified out-of-scope file, its output was byte-identical.
- A temp-index rebuild **does** write into `.git/objects` — 8 to 12 loose objects with
  novel content. A temporary index protects the real index, not the object database, so
  the reviewer cannot take the git path for drift checks without writing to the
  repository.

**The mailbox is excluded from the environment fingerprint.** It lives inside the
repository, so without an explicit exclusion the act of publishing a handoff writes
into `.coord/`, that write lands in the fingerprint, and the handoff invalidates the
review it is carrying. This was found by end-to-end testing after every unit test
passed — the helpers were each correct in isolation and wrong in composition.

Either drift invalidates the verification. Approval identifies the snapshot;
continuation re-confirms the working tree still matches it. If it does not, the
approval no longer applies and a fresh handoff is required. The git snapshot remains
readable throughout — `git diff base..snapshot` reads existing objects and creates
none.

## Approval semantics

- An approval **names the snapshot it approves** and releases dependent work for that
  snapshot only.
- **Acknowledgement is not approval. Silence is not approval. A timeout is not
  approval.**
- `changes-requested` produces fixes, then a **revision** handoff with a **new**
  snapshot, then a new review. The cycle repeats; approvals never carry across
  revisions.

## Crash recovery

`state/<role>.json` records processed message ids **and the ids of the responses each
produced**:

```json
{ "last_read": "<id>",
  "processed": [ { "message": "<id>", "action": "reviewed",
                   "responses": ["<id>"], "at": "<iso>" } ] }
```

There are **two** crash windows, and recovery must handle both:

- **Acted, not recorded.** A journal entry names an action with no published response:
  the action was interrupted. Inspect its actual state and report it; do not repeat it
  blindly.
- **Published, not journalled.** The response reached the mailbox and the session died
  before the journal was written. Recovery must *discover* it — scan the mailbox for
  messages authored by this role whose `reply_to` names the message in question — and
  reconcile the journal. Without this the agent republishes a duplicate response, or
  redoes implementation work that already landed.

Journal updates are **atomic replacements**: write to `tmp/`, then `mv` over the
journal. This is the one place `mv` is correct — the journal is mutable and must be
replaced, where a published message is immutable and must never be.

The protocol claims at-least-once delivery with reconciliation. It does not claim
exactly-once execution, and declaring actions "idempotent" would not make it so.

Both windows are exercised by interrupting deliberately at each point. A normal
session restart exercises neither.

## Escalation to the human

A `question` message escalates. Both agents **pause dependent work** while keeping
their declared monitoring or resumption mechanism alive — an agent that simply stops
may never learn the answer without another human nudge, which is the problem this
protocol exists to remove.

**The human's conversational answer is authoritative the moment it is given.** The
protocol is a delivery mechanism; it holds no authority over the human's instructions.

- The receiving agent records the answer as a `decision` message, preserving its
  meaning, linking it to the question through `reply_to`, and naming the checkpoint
  that resumes.
- **Coordinated** dependent work waits until publication succeeds, so the counterpart
  acts from the same record.
- If publication fails, the agent **reports the failure**. It never asks the human to
  repeat an answer already given.
- Stop and cancellation instructions take effect **immediately**, whether or not
  recording succeeds.

## Visibility

The point of the run is that the human can watch it without opening files.

A short **user-facing** block — in the reply text, not stdout buried in collapsed tool
output — is required on exactly five events: publishing a handoff, receiving findings,
requesting a decision, completing a checkpoint, and escalating.

```
Checkpoint 1 · snapshot 622817e · changes-requested
Next: addressing 3 findings, then revision handoff
.coord/2026-09-15-.../messages/20260915T0702Z-reviewer-review-4f1a.md
```

Empty polls print nothing. A wait that times out prints one status line, and only if
the agent is stopping.

## Helpers

Deterministic scripts, not procedures reconstructed from prose by each agent:

| Script | Role | Writes |
|---|---|---|
| `coord-snapshot` | implementer | git objects + `refs/coord/<run>/<msg>` |
| `coord-manifest` | both | nothing (canonical serializer; Python, not shell) |
| `coord-verify` | reviewer | nothing |
| `coord-publish` | both | one mailbox message (link, never replace) |
| `coord-check` | both | the role's own cursor/journal |
| `coord-end` | implementer | follows the declared retention policy (`keep-refs`, `bundle`, `discard`) |

## Packaging

```
agent-coordination/
  docs/2026-09-15-agent-coordination-protocol-design.md   this document
  PROTOCOL.md                                             the single authority
  bin/coord-*                                             helpers
  shims/claude/SKILL.md                                   → ~/.claude/skills/coordinate/
  shims/codex/SKILL.md + agents/openai.yaml               → ~/.agents/skills/coordinate/
```

Invocation: `/coordinate <verb> <role>` (Claude), `$coordinate <verb> <role>` (Codex).
Verbs: `start`, `join`, `handoff`, `review`, `check`, `wait`, `ask`, `decide`,
`status`, `end`.

## Trial

Test project: Byline CMS, `specs/2026-09-14-embedded-relation-creation-plan.md`,
Part I, Task 1, Checkpoint 1. Claude implements; Codex reviews.

It is not proven until one run has exercised:

1. A handshake **amendment**, accepted by both sides.
2. One `changes-requested` round producing a fresh revision snapshot.
3. **Both crash windows**, induced deliberately — an action interrupted before its
   response is published, and a response published before the journal is written. A
   normal session restart exercises neither, so it does not count.
4. Drift detection firing at least once, deliberately — including one mode-only or
   symlink-only change, since those are the cases the first design missed.

Only then does it extend to Checkpoints 2–7, and only then is independent parallel
work considered — isolation must be proven before concurrency is allowed.

## Open questions

1. **Codex personal-skill discovery.** Documentation says `$HOME/.agents/skills/`;
   this installation has `~/.codex/skills/` and its bundled installer targets
   `$CODEX_HOME/skills`. `~/.agents/skills/` does not currently exist. Install to the
   documented location, then **verify `coordinate` actually appears** in Codex's
   available skills before the trial begins. Do not install duplicates.
2. Whether the canonical workspace becomes a git repository now or later.
3. Whether run transcripts are retained by default, or only on request.

## Verified evidence

Every claim below was tested in a scratch repository, not reasoned about. Equality
claims hold **for the fixtures listed** — a filename containing a newline, a symlink
target ending in a newline, a mode/name ordering conflict, a deleted-but-cached
tracked file — and these fixtures carry into the helper's test suite. They are not a
proof of equivalence over all inputs.

| Claim | Result |
|---|---|
| Scoped snapshot excludes out-of-scope and ignored files | confirmed |
| Snapshot leaves `HEAD`, branch, index untouched | confirmed, `git status` identical |
| `refs/coord/...` survives `git gc --prune=now` | confirmed |
| `mv` silently clobbers a published message | confirmed |
| `ln` refuses to replace one | confirmed, `File exists` |
| Same-second ids collide without a random suffix | confirmed, 3 of 3 identical |
| `git status --porcelain` is not a content fingerprint | confirmed, byte-identical across a real change |
| Temp-index rebuild writes to `.git/objects` | confirmed, 8 → 12 loose objects |
| Content manifest detects drift and writes nothing | confirmed |
| Per-file digest misses an executable-bit change | confirmed, false negative |
| Per-file digest misses a symlink repointed between identical-content files | confirmed, false negative |
| Tree-line record format (mode + symlink target) catches both | confirmed |
| `git hash-object` without `-w` writes no objects | confirmed, 6 → 6 — superseded; the helper computes ids directly |
| Shell worktree loop matched `git ls-tree -r <snap>` on *simple* fixtures only | withdrawn — it fails on the adversarial fixtures below |
| `readlink`'s trailing newline breaks symlink hashes | confirmed — shell ate a newline while *creating* a fixture |
| Shell tree-vs-worktree digests differ on adversarial fixtures | confirmed, `d477af…` vs `781816…` |
| Canonical serializer agrees across all four adversarial fixtures | confirmed, identical digest |
| Deleted-but-cached tracked file yields an absent entry, not a corrupt record | confirmed |
| Unreadable file aborts the manifest with a non-zero exit | confirmed, exit 1, path named |
| Missing declared ignored input is stable, and its creation is detected | confirmed |
| `.gitattributes` `text`/`filter`/`eol` refused up front | confirmed |
| Serializer writes no git objects | confirmed, 13 → 13 |
| Publishing a handoff invalidated its own review | confirmed — found only in composition; fixed by excluding the mailbox |
| Full handoff → changes-requested → revision → approved cycle | confirmed end-to-end |
| Both crash windows recover correctly in a live run | confirmed end-to-end |
| An all-zero snapshot id "verified" | confirmed — verification did not read the snapshot; now bound to it |
| A retried publish truncated an immutable message | confirmed — predictable staging name; now exclusive per attempt |
| `git status` rewrote the real index during review | confirmed — now `GIT_OPTIONAL_LOCKS=0` |
| A `question` closed the review it asked about | confirmed — only completing reply types resolve a parent |
| A declared ignored input widened the env scope to `.` | confirmed — mailbox re-entered through the fallback |
| The test runner reported success for a failing suite | confirmed — it read `tail`'s status; canary now exits 1 |
