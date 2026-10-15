# agent-coordination

Two independent agent sessions — different harnesses, no shared process — working on
one repository: one implementing, one reviewing, exchanging handoffs and reviews
through a mailbox on the shared filesystem instead of through a human copying text
between applications.

| Path | What it is |
|---|---|
| `PROTOCOL.md` | The single authority. Both harness shims defer to it. |
| `bin/` | Six helpers. No dependencies beyond Python 3 and git. |
| `shims/claude/` | Installed at `~/.claude/skills/coordinate` (symlink) |
| `shims/codex/` | Installed at `~/.agents/skills/coordinate` (symlink) |
| `tests/run` | Every unit suite |
| `tests/smoke` | A full cycle end-to-end against a real repository |
| `docs/` | Design, with the evidence behind each rule |

The project being coordinated gets a mailbox at `<project>/.coord/<run-id>/`, ignored
through `<project>/.git/info/exclude` — local and uncommitted. Nothing else is added
to it. Plan paths, checkpoints, review scope and verification commands are supplied at
invocation, never hardcoded.

## Install

```sh
ln -s "$PWD/shims/claude" ~/.claude/skills/coordinate   # Claude Code
ln -s "$PWD/shims/codex"  ~/.agents/skills/coordinate   # OpenAI Codex
```

Claude Code invokes the skill as `/coordinate`; Codex as `$coordinate`. The Codex
shim sets `allow_implicit_invocation: false`, so it only runs when named.

## Usage

Open one session of each harness in the project being coordinated. Roles are
assigned by you at invocation — either harness can take either role.

### Claude Code implementing, Codex reviewing

Start the run in Claude Code, supplying the plan, checkpoints and verification
commands. It initialises the mailbox and publishes the handshake:

```
/coordinate start implementer
  run: 2026-10-16-auth-refactor
  plan: docs/plans/auth-refactor.md
  checkpoints: after task 2 (scope src/auth/), after task 5 (scope src/ tests/)
  verification: pnpm test (mutates: none), pnpm lint (mutates: source)
```

Join from Codex, which replies with a `handshake-ack`:

```
$coordinate join reviewer 2026-10-16-auth-refactor
```

Then, as the run progresses:

| Claude Code (implementer) | Codex (reviewer) |
|---|---|
| `/coordinate handoff` — snapshot and publish checkpoint 1 | `$coordinate wait` — block until the handoff lands |
| `/coordinate wait` — block until the review lands | `$coordinate review` — verify the snapshot, publish findings |
| `/coordinate check` — pick up findings, revise | `$coordinate check` — pick up the revision |
| `/coordinate status` | `$coordinate status` |
| `/coordinate end` — apply the retention policy | |

### Codex implementing, Claude Code reviewing

The same verbs with the roles swapped:

```
$coordinate start implementer
  run: 2026-10-16-billing-export
  plan: docs/plans/billing-export.md
  checkpoints: after task 3 (scope src/billing/)
  verification: cargo test (mutates: artifacts), cargo fmt (mutates: source)
```

```
/coordinate join reviewer 2026-10-16-billing-export
```

### Launching from the shell

Either harness can be started with the invocation as its first prompt. Single-quote
the Codex prompt so the shell leaves `$coordinate` alone:

```sh
claude "/coordinate start implementer run: 2026-10-16-auth-refactor plan: docs/plans/auth-refactor.md"
codex '$coordinate join reviewer 2026-10-16-auth-refactor'
```

### Questions and decisions

Either agent can escalate with `ask`; both pause dependent work. Answer in whichever
session is convenient — that agent records your answer as a `decision`:

```
/coordinate ask should the session store migrate in place or behind a flag?
$coordinate decide behind a flag; resume checkpoint 2
```

### Waiting

Each harness declares its own wait bound in the handshake: 600 seconds for Claude Code
(via the Monitor tool), 60 seconds for Codex (one bounded shell loop). A timeout is
never an approval — re-run `wait` or `check` to keep going.

## Tests

```sh
tests/run && tests/smoke
```
