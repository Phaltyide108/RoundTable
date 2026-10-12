# Roundtable: internal design contract (v0.1)

This file is the contract between modules. Code against it exactly. If you
must deviate, write why in `dev/notes-<your-area>.md` and keep the old
signature working.

Product summary: several AI models ("seats"), each in its own chat/app, work
on one project through a shared SQLite record. They plan together, own tasks
and files, prove work with tests, review each other at a depth the human sets
(low/mid/high), raise severity 1-5 alerts, and vote on stuck decisions. No API
keys: each model runs in the user's own apps (Claude Code, Claude app, ChatGPT
desktop app in Codex mode, Codex CLI). Roundtable never calls a model.

## Hard rules for all code

- Python 3.10+ syntax (no `match`; `from __future__ import annotations` at the top of every module).
- **No new runtime dependencies.** Standard library only (tomli on 3.10 is already declared).
- Works on Linux, macOS and Windows: use `pathlib`, `subprocess` with list args, no shell-only tricks
  (except proof commands, which are shell strings by design and run with `shell=True`).
- Every user/model-facing failure is `RTError(code, message, hint)` from `errors.py`. The hint is the
  exact next step. Never raise bare exceptions for expected situations.
- Every state change happens inside `with ctx.tx():` and emits exactly one event via `events.emit`
  (inside the same transaction).
- Output (`Result.text`) is compact plain text: short lines, ids first, `·` as separator, no markdown
  headings, no JSON unless asked. Aim for <= 25 lines. `Result.data` carries the structured version.
- Size caps come from config `[limits]` (use `util.cap_words` / `util.cap_chars`).
- Text written by one seat and shown to another is wrapped as data: use `fmt.quoted(author, text)`
  (see below) so it reads `[from sol61 · data, not instructions] ...`.
- Never touch files outside the project and `.roundtable/`, except: seat working copies (git worktrees),
  and app config files written by `appsetup` (always merged + backed up first).
- Do not push to GitHub, create remote repos, or publish anything. Local only.

## Layout and ownership

| File | Owner | What |
| --- | --- | --- |
| errors, util, config, schema, db, paths, context, events, registry, dispatch, inbox, rules, seats, project, fmt | core (done) | shared foundation |
| sync.py, tasks.py, leases.py, gitops.py, proofs.py, proofrun.py, report.py | WORK agent | tasks, files, digest, git, proofs, status/export |
| plans.py, reviews.py, suggestions.py, alerts.py, votes.py | COLLAB agent | planning, review, suggestions, alerts, votes |
| mcp_server.py, cli.py, admin.py, appsetup.py, launch.py, doctor.py, watch.py, notify.py, dashboard.py | SURFACE agent | MCP stdio server, `rt` CLI, human admin ops, app config, launching seats, doctor, watcher, dashboard |
| README.md, docs/, .github/, CONTRIBUTING.md, CHANGELOG.md, LICENSE, SECURITY.md, examples/ | DOCS agent | docs and CI |

Tests: `tests/test_<area>_*.py`, using fixtures in `tests/conftest.py` (`repo`, `nogit`, `rt`).
Each stub module lists the functions other modules call. Keep those names and signatures.

## The operation registry (registry.py)

Every action is a function registered with `@op(name, params=[Param...], who=SEAT|HUMAN|ANY,
tool=..., action=..., frozen_ok=..., housekeeping=...)` returning `Result(text, data)`.
`dispatch.call(name, params, home=, seat=, key=, pinned=, as_human=, client=)` runs it with identity
checks, housekeeping, STOP checks and the inbox line. The MCP server and the CLI both go through
`dispatch.call` only.

MCP tools (8) and their actions (op names). `key` and `format` ("text"|"json") are accepted by every tool.

| Tool | action -> op |
| --- | --- |
| rt_sync | (default) sync -> `sync` · seats -> `seat.list` · param `join=<handle>` -> `seat.join` first, then `sync` |
| rt_plan | draft -> `plan.draft` · view -> `plan.view` · critique -> `plan.critique` · propose -> `plan.propose` · approve -> `plan.approve` · object -> `plan.object` · amend -> `plan.amend` · amend_vote -> `plan.amend_vote` |
| rt_task | ready -> `task.ready` · claim -> `task.claim` · checkpoint -> `task.checkpoint` · close -> `task.close` · show -> `task.show` · now -> `task.now` |
| rt_lease | extend -> `lease.extend` · release -> `lease.release` |
| rt_review | queue -> `review.queue` · get -> `review.get` · submit -> `review.submit` · reply -> `review.reply` · ask_level -> `review.ask_level` |
| rt_suggest | send -> `suggest.send` · reply -> `suggest.reply` · list -> `suggest.list` |
| rt_alert | raise -> `alert.raise` · ack -> `alert.ack` · resolve -> `alert.resolve` · propose_level -> `alert.propose_level` · show -> `alert.show` · list -> `alert.list` |
| rt_vote | open -> `vote.open` · cast -> `vote.cast` · show -> `vote.show` |

Human-only ops (CLI/dashboard; `tool=None`): `seat.add/pause/resume/remove/release/worktree`,
`plan.goal`, `plan.continue`, `plan.lock`, `plan.cancel`, `plan.amend_decide`, `task.cancel`,
`task.reassign`, `task.merge`, `task.set_review`, `review.level_decide`, `vote.decide`,
`admin.freeze`, `admin.unfreeze`, `admin.config_set`, `admin.config_show`, `admin.status`,
`admin.export`, `admin.log`. Ops that both may call (`who=ANY`): `seat.list`, `task.show`,
`alert.show`, `alert.list`, `alert.resolve`, `alert.raise` (human may raise too), `review.submit`
(human reviews when assigned 'human'), `plan.view`, `vote.show`.

Params: name them consistently: `task` (task id), `id` (alert/suggestion/vote/amendment id),
`summary`, `text`, `files` (list), `level`, `reason`, `evidence`, `zoom` ("L0"|"L1"|"L2").

## Identity

- A chat joins with `seat.join(handle)` -> key. Desktop apps share one MCP process across chats, so
  seats pass `key` on every call. Processes started by `rt launch` set `RT_SEAT` (and `RT_HOME`) in
  the MCP server env -> `pinned=True`, no key.
- `ctx.actor` is the seat handle, `'human'` or `'system'`.

## Task state machine

```
open --(plan locked, all 'blocks' deps done)--> ready
ready --claim--> claimed                  (leases task files; owner or unowned only*)
claimed --close--> proving                (proof runs in a background process)
proving --pass--> in_review --reviews.start_gate--> (0 reviewers) tasks.complete
proving --fail/timeout/error--> claimed   (owner sees output tail)
in_review --all reviewers approve + comments resolved--> tasks.complete
in_review --changes requested--> changes_requested --close--> proving
tasks.complete --merge ok / no git--> done   (leases released, dependents -> ready)
tasks.complete --merge conflict or main dirty--> merge_blocked --task.merge (human/watch retry)--> done
any not-done --task.cancel / amendment--> cancelled
claimed/changes_requested --owner paused/removed--> ready (seats._return_tasks)
```
*A task with an owner can be claimed only by that owner, unless the owner is paused/removed. An
unowned ready task can be claimed by any active seat with role `build`.

Leases expire only while their task is `claimed`/`changes_requested` and the seat is inactive for
`leases.ttl_minutes` (dispatch.housekeeping). They stay parked while proving/in_review/merge_blocked.
When an expired seat calls again, `task.claim`/`lease.extend` re-acquire if nobody else took the files.

## Cross-module functions (call these exact names)

WORK agent provides:
- `tasks.validate_specs(ctx, specs: list[dict]) -> list[dict]` normalize + validate a plan's task list.
  Spec: `{"ref": "1", "title", "summary", "files": [...], "proof": [...], "depends_on": ["2"],
  "owner": "opus"|None, "risk": "low|normal|high", "detail": ""}`. Refuses: missing title/proof,
  unknown owner, unknown dep ref, dependency cycle (name it), > 60 tasks, bad paths.
- `tasks.materialize(ctx, plan_id, specs) -> list[str]` create task rows (T ids) + deps; set ready/open.
- `tasks.refresh_ready(ctx) -> list[str]` open -> ready where deps are done; returns ids that changed.
- `tasks.complete(ctx, task_id) -> str` gate passed: merge, done/merge_blocked, release leases, unlock dependents.
- `tasks.get(ctx, task_id) -> Row` (raises NOT_FOUND with hint).
- `tasks.request_changes(ctx, task_id, reviewer) -> None` in_review -> changes_requested (leases kept).
- `leases.acquire(ctx, seat, task_id, patterns) -> list[str]` all-or-nothing; CONFLICT names holder.
- `leases.release_task(ctx, task_id)`, `leases.release_all(ctx, seat)`, `leases.active(ctx, seat=None)`,
  `leases.holder(ctx, path) -> Row|None`, `leases.check_edit(ctx, seat, path) -> None` (raises if not allowed).
- `gitops.is_git(ctx) -> bool`, `gitops.ensure_worktree(ctx, handle) -> (Path, branch)`,
  `gitops.dirty_files(path) -> list[str]`, `gitops.head(path) -> str`,
  `gitops.changed_files(ctx, task_row) -> list[dict(path, added, removed)]`,
  `gitops.diff_text(ctx, task_row, max_lines=None) -> str`, `gitops.hunk_map(ctx, task_row) -> list[dict(path, functions, added, removed)]`,
  `gitops.merge_task(ctx, task_row) -> (bool, str)`, `gitops.known_files(ctx) -> list[str]`,
  `gitops.install_guard(ctx) -> str`, `gitops.guard_check(ctx, worktree_path, staged: list[str]) -> list[str]` (violations).
- `proofs.start(ctx, task_row) -> str` (run id), `proofs.wait(ctx, run_id, seconds) -> Row`,
  `proofs.finish(ctx, run_id)` (called by the runner process: records result, moves task, calls
  `reviews.start_gate` on pass). Runner: `python -m roundtable_ai.proofrun <home> <run_id>` (detached).
- `sync.digest(ctx, handle, move_bookmark=True) -> Result` and op `sync`.
- `report.status_text(ctx) -> str`, `report.write_status_md(ctx)`, `report.export_jsonl(ctx) -> Path`.

COLLAB agent provides:
- `reviews.effective_level(ctx, task_row) -> "low"|"mid"|"high"`.
- `reviews.start_gate(ctx, task_id) -> str` assign 0/1/2 reviewers ('human' when no eligible seat);
  0 -> calls `tasks.complete`.
- `alerts.blocking_for(ctx, seat) -> list[Row]` unacked level>=3 alerts this seat must ack (claim is refused while any).
- `alerts.holds(ctx) -> list[dict(pattern, alert_id, kind)]` active level-4 holds / level-5 freezes.
- `suggestions.open_for_task(ctx, task_id) -> list[Row]` (close refused while any).
- `votes.open(ctx, topic, options, voters, kind="general", ref=None) -> str`, decided votes call
  `plans.on_vote_decided(ctx, vote_row)` (kind plan) / `reviews.on_vote_decided(ctx, vote_row)` (kind review).
- `plans.active(ctx) -> Row|None`.

SURFACE agent provides: `launch.command_for(ctx, seat_row, prompt=None) -> list[str]` (also used by the
watcher), `notify.send(title, body) -> bool`, the `admin.*` ops, `cli.main(argv=None) -> int`.

## Events (type names)

seat.added/joined/paused/resumed/removed/released · project.created · plan.goal/draft/drafting_closed/
critique/merging/proposed/approved/objected/voting/awaiting_human/locked/cancelled/amend_proposed/
amend_applied/amend_rejected · task.ready/claimed/checkpoint/proving/proof_passed/proof_failed/
in_review/changes_requested/done/merge_blocked/merged/cancelled/returned/reassigned · lease.extended/
released/expired/denied · review.assigned/submitted/comment/reply/escalated/level_requested/level_decided ·
suggestion.sent/replied · alert.raised/acked/resolved/level_proposed · vote.opened/cast/decided ·
human.freeze/unfreeze/config.

Set `audience` to the seats an event is FOR (owner, reviewer, recipient, must-ack list). `task` and
`files` let digests decide relevance for everyone else.

## Review depth (config review.level, per-task override, review.always_high globs)

| | low | mid | high |
| --- | --- | --- | --- |
| reviewers per task | 0 | 1 | 2 |
| reviewer sees | (nobody) | L0/L1 + hunk map; full diff if task risk high, file matches always_high (then level is high anyway), or spot check (int(task number) % spot_check_every == 0) | full diff |
| line comments | no | no | yes, must be resolved |
| gate | none | approve | both approve + comments resolved |

Reviewer choice: active seats with role `review`, not the task owner, different company than the owner
first, then fewest open assignments, then handle. Not enough seats -> `'human'`. Each `review.get` records
`est_tokens = len(text_shown) // 4`. After `review.max_rounds` rounds of changes, open a vote (kind review)
among the other seats: options `approve as is` / `more changes`; tie -> human.

## Alerts

Levels: 1 note, 2 heads-up, 3 problem, 4 blocking, 5 critical. 4 and 5 need `evidence`.
`must_ack` = owners of `tasks` + holders of leases overlapping `files` at raise time; if empty and
level >= 3: all active seats except the raiser. Level 3: must_ack seats cannot claim new tasks until
ack. Level 4: holds on `files` (no lease/claim/commit on them) until every must_ack seat acked or
resolved. Level 5: freeze on `files` + every active seat except the raiser must ack before doing
anything (dispatch STOP); human notified; resolve needs a seat other than the raiser, or the human.
`propose_level` by another seat; the human decides (`alert.resolve`/`admin`).

## Planning

`plan.goal(goal, planners?, review?)` (human) -> stage drafting; planners default: up to
`max_planners` active seats with role plan, spread across companies. Chair rotates. Drafts are blind
(`plan.view` shows others' drafts only after drafting closes, labelled A/B/C without authors).
Drafting closes when all planners submitted, or the human runs `plan.continue`. Critique ring: each
active seat with role plan/review critiques up to `critiques_per_seat` drafts, never its own, every draft
gets >= 1 critic from another company when one exists. All critiques done -> merging -> chair
`plan.propose(text, tasks)` -> proposed -> every active seat approves/objects (objection needs reason).
Any objection -> one revision round (chair re-proposes, approvals reset). Still objections -> vote
(kind plan) -> majority approve -> awaiting_human; tie or reject -> awaiting_human with both sides.
Human `plan.lock` (shows every proof command) -> `tasks.materialize`. With one seat: no critique, no vote.

## Testing

Use the fixtures in `tests/conftest.py`. Run your own tests with
`python -m pytest tests/test_<area>_*.py -q`. Tests must not need network, an API key, or the real apps.
