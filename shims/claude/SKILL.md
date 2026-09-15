---
name: coordinate
description: Coordinate implementation and review with a second, independent agent session over a shared-filesystem mailbox. Use when work is split between two agents — one implementing, one reviewing — so handoffs, reviews, approvals and decisions are exchanged directly instead of the human copying text between applications. Invoke as /coordinate <verb> <role>, e.g. "coordinate start implementer", "coordinate check", "coordinate handoff".
---

# Coordinate with another agent session

**Read `~/Clients/Infonomic/Projects/agent-coordination/PROTOCOL.md` in full before
acting.** It is the single authority; everything below is Claude Code specifics.

```sh
COORD_HOME=/Users/tony/Clients/Infonomic/Projects/agent-coordination
PATH="$COORD_HOME/bin:$PATH"
```

## Verbs

`start` · `join` · `handoff` · `review` · `check` · `wait` · `ask` · `decide` ·
`status` · `end`

Roles are assigned by the human at invocation. **Never infer your role** from which
session opened first, and never negotiate it with the other agent.

## Mailbox placement

`<project>/.coord/<run-id>/`, ignored through `<project>/.git/info/exclude` — local
and uncommitted, so the coordination leaves no trace in the project's history. Do not
edit a tracked `.gitignore` for this, and do not add protocol files to the project.

```sh
coord-check --mailbox "$PWD/.coord/$RUN" --role "$ROLE" --init
grep -qx '.coord/' .git/info/exclude || echo '.coord/' >> .git/info/exclude
```

## Waiting, on this harness

Declare `active-wait` with a bound of **600 seconds** — the Bash tool's ceiling.

Foreground `sleep` is blocked in this harness, so do not write a polling loop with
`sleep`. Use the **Monitor** tool with an until-condition on `coord-check` output
(load it with `ToolSearch` first). If Monitor is unavailable, do one bounded check,
print a status line, and stop rather than spinning.

A timeout changes waiting state only. It never releases dependent work and never
implies approval.

## Visibility — required

Text you write outside tool calls is what the human sees; stdout inside a tool result
is usually collapsed. So print the five-event block **in your reply text**, not by
echoing it in a shell command:

```
Checkpoint 1 · snapshot 622817e · changes-requested
Next: addressing 3 findings, then revision handoff
.coord/<run>/messages/<id>.md
```

Required on: publishing a handoff, receiving findings, requesting a decision,
completing a checkpoint, escalating. Silent on empty polls.

## As implementer

You own implementation files, the index, and branch refs. Pause work at a handoff and
during snapshot capture. `coord-snapshot` writes git metadata — that authorization is
separate from, and does not imply, authorization to commit onto the branch. Ask before
committing if the human gates commits.

## As reviewer

Write nothing but mailbox messages and your own journal. Before running any
verification command, check the handshake's `mutates:` column — a command named
`lint` may rewrite the code you are reviewing. Run `coord-verify` before and after
verification, and report drift as drift.

## If you need the human

Publish a `question`, print it in your reply, and pause dependent work while keeping
your wake mechanism alive. Their conversational answer is authoritative immediately —
record it as a `decision`, and if that fails, report the failure rather than asking
them to repeat themselves.
