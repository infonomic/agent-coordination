---
name: coordinate
description: Coordinate implementation and review with a second, independent agent session over a shared-filesystem mailbox. Use when work is split between two agents — one implementing, one reviewing — so handoffs, reviews, approvals and decisions are exchanged directly rather than copied between applications by the user. Invoked as $coordinate <verb> <role>.
---

# Coordinate with another agent session

**Read `/Users/tony/Clients/Infonomic/Projects/agent-coordination/PROTOCOL.md` in full
before acting.** It is the single authority; everything below is Codex specifics.

```sh
COORD_HOME=/Users/tony/Clients/Infonomic/Projects/agent-coordination
PATH="$COORD_HOME/bin:$PATH"
```

## Verbs

`start` · `join` · `handoff` · `review` · `check` · `wait` · `ask` · `decide` ·
`status` · `end`

Roles are assigned by the user at invocation. **Never infer your role** from which
session opened first, and never negotiate it with the other agent.

## Mailbox placement

`<project>/.coord/<run-id>/`, ignored through `<project>/.git/info/exclude`. The
protocol directory may be read-only under your sandbox — that is expected. You need
write access only to the project mailbox and, as implementer, to the project itself.

## Waiting, on this harness

Declare `active-wait` with a bound of **60 seconds**, matching this session's own
instruction against longer blocking waits, or `scheduled-resume` if a scheduled
follow-up is available and the run is long. State which you actually have; do not
declare a capability you have not verified.

A bounded wait is one shell call, not one model turn per filesystem check:

```sh
end=$(( $(date +%s) + 55 ))
while [ "$(date +%s)" -lt "$end" ]; do
  ids=$(coord-check --mailbox "$MAILBOX" --role "$ROLE") || exit 1
  [ -n "$ids" ] && { printf '%s\n' "$ids"; exit 0; }
  sleep 5
done
exit 3   # timeout: waiting state only, never approval
```

## Visibility — required

Print the five-event block as a user-facing message, not only as command output:

```
Checkpoint 1 · snapshot 622817e · changes-requested
Next: addressing 3 findings, then revision handoff
.coord/<run>/messages/<id>.md
```

Required on: publishing a handoff, receiving findings, requesting a decision,
completing a checkpoint, escalating. Silent on empty polls.

## As reviewer

You write mailbox messages and your own journal — nothing else. Never modify
implementation files, the real index, or any git reference. Before running any
verification command, check the handshake's `mutates:` column rather than inferring
from the command's name. Run `coord-verify` before and after verification, and report
drift as drift, never as a pass.

## As implementer

You own implementation files, the index, and branch refs. Pause at a handoff and during
snapshot capture. Minting a snapshot writes git metadata; that is separate from
authorization to commit onto the branch.

## If you need the user

Publish a `question`, surface it, and pause dependent work while keeping your wake
mechanism alive. Their conversational answer is authoritative immediately — record it
as a `decision` linked to the question; if recording fails, report the failure rather
than asking them to repeat it. Stop instructions take effect immediately regardless.
