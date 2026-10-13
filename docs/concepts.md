# Concepts

## Seats

A **seat** is one model in one chat. You register it once:

```bash
rt seat add opus --model claude-opus-5-5 --app claude-code
```

- `--model` is the model name the app understands. It is passed to the app's `--model` option by `rt launch`.
- `--app` is where the seat runs: `claude-code`, `claude-app`, `codex-cli`, `codex-app` (ChatGPT desktop, Codex mode) or `other`.
- The company (anthropic, openai, google, ...) is guessed from the app and model; pass `--company` if it can't be. Reviews prefer a reviewer from a different company than the author.
- Roles: `plan`, `build`, `review` (all by default). Claude app seats can't edit files, so they plan and review only.
- Coding seats get their own git working copy next to the project (`../project.opus`), resting on branch `rt/opus/idle`.

A chat **takes** a seat by joining: `rt_sync join="opus"`. It gets a short key to pass on every call. A seat can be live in only one chat at a time. If a chat closed without warning, free the seat with `rt seat release opus`. Seats started with `rt launch` are bound to their seat automatically and need no key.

## Plans

`rt goal "..."` starts a plan. The stages are:

```text
drafting -> critique -> merging -> proposed -> (voting) -> awaiting_human -> locked -> done
```

- **drafting:** up to 3 planners (spread across companies) each submit a draft of up to 300 words plus a task list. Drafts are blind until all are in. If one is late, `rt plan continue` moves on without it.
- **critique:** drafts become Draft A, B, C with no author shown. Each seat critiques up to 2 drafts, never its own, with keep / change / drop points.
- **merging:** the chair (rotates between plans) proposes one merged plan.
- **proposed:** every other planning or reviewing seat approves or objects (objections need a reason). One revision round; if objections remain, the seats vote.
- **awaiting_human → locked:** you run `rt plan lock`, which lists every test command you are approving. Tasks are created.

After the lock, seats propose changes with amendments: renaming a task is immediate; structural changes need the chair and the affected owners; changing a test command also needs you.

## Tasks

Each task has a title, a summary, the files it may edit, one or more **proof** commands, dependencies, an optional owner and a risk level.

```text
open -> ready -> claimed -> proving -> in_review -> done
                   ^          |            |
                   +--(fail)--+            +-> changes_requested -> (close) -> proving
                                           +-> merge_blocked -> (rt task merge) -> done
```

- **ready:** all tasks it depends on are done.
- **claimed:** a seat claimed it. Its files are leased to that seat, and its working copy switches to branch `rt/<seat>/<task>`.
- **proving:** the seat closed it; Roundtable runs the proof in the background.
- **in_review:** the proof passed; reviewers are assigned at the current depth.
- **done:** reviews passed and the task's proven commit is merged into your main branch.
- **merge_blocked:** waiting to merge, because your main folder has uncommitted changes or there is a conflict.

## Leases

Claiming a task leases its files (paths or globs like `src/api/**`). Other seats can read those files and send suggestions, but can't lease or commit them. Leases renew whenever their seat does anything, and expire after 30 minutes of inactivity while the task is being worked on. While a task waits for proof, review or merge, its leases stay put.

## Proofs

A task's proof commands come from the plan you approved and are run by Roundtable itself, never taken from a message. They run in the seat's working copy, in a separate background process, with a time limit (15 minutes per command by default), `CI=1` set, and the last 40 lines of output kept. A long proof never times out a model's tool call: close answers "running" and the result arrives in the digest.

## Reviews

See [the README](../README.md#review-depth) for the depth table. Reviewers come from a different company than the author when possible, then the least busy seat. If no seat can review, the review goes to you (`rt review queue`). After 3 rounds of changes, the seats vote whether to accept the task as it is; a tie goes to you.

## Suggestions

A seat that wants a change in a file it doesn't own sends a suggestion to the owner. The owner must answer every suggestion (accepted, rejected or later, with a reason) before closing that task.

## Alerts

Severity 1 to 5. See [the README](../README.md#alerts). Levels 4 and 5 need evidence. A level-5 alert freezes its files and makes every other seat acknowledge before doing anything else. Another seat (not the one that raised it) or you must resolve it.

## Votes

For decisions the seats can't settle. Every ballot needs a reason, so the vote doubles as the argument. When all voters have voted, the most votes wins; a tie goes to you (`rt vote decide`).

## The digest

`rt_sync` shows a seat only what changed since it last looked: full lines for anything touching its tasks, files or dependencies, one folded line per other seat for the rest, then what needs it now. It is built by plain code, so it costs no model tokens to produce.
