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

```sh
tests/run && tests/smoke
```
