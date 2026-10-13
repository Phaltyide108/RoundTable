# Architecture (for contributors)

Roundtable is a plain Python package with no third-party runtime dependencies. Everything goes through one path:

```text
MCP server (mcp_server.py) ─┐
CLI (cli.py) ───────────────┼─> dispatch.call(op, params, identity) ─> registered operation ─> SQLite + git
dashboard (dashboard.py) ───┘
```

## Modules

| Module | Role |
| --- | --- |
| `registry.py` | `@op` decorator, parameter validation, tool/action mapping |
| `dispatch.py` | identity checks, lease housekeeping, STOP checks, inbox line, error logging |
| `db.py`, `schema.py` | SQLite store (WAL, busy timeout, `BEGIN IMMEDIATE` transactions), schema and migrations, newer-version guard |
| `config.py` | validated settings with typo suggestions; edits keep comments |
| `seats.py`, `rules.py` | seats, join keys, the rules card |
| `plans.py` | goal, blind drafts, critique ring, proposals, approvals, votes, lock, amendments |
| `tasks.py`, `leases.py` | task state machine, claims, checkpoints, close; file leases |
| `proofs.py`, `proofrun.py` | detached proof runner, time limits, output caps, dead-runner detection |
| `reviews.py` | review depth, reviewer choice, review material, gate, line comments |
| `suggestions.py`, `alerts.py`, `votes.py` | the rest of the collaboration features |
| `gitops.py`, `guard.py` | worktrees, task branches, diffs, hunk maps, merges, the pre-commit guard |
| `sync.py`, `inbox.py`, `report.py` | digests, inbox lines, status, exports |
| `appsetup.py`, `launch.py`, `doctor.py`, `watch.py`, `notify.py` | connecting apps, starting seats, health checks, timing |

## Why a hand-written MCP server

The official Python SDK renamed its server API between 1.x and 2.x. The part of the protocol Roundtable needs (initialize, tools/list, tools/call, ping) is small and stable, so speaking it directly removes a source of install-time breakage. Clients using the newer 2026-07-28 protocol first send `server/discover`; Roundtable answers "method not found", which makes them fall back to `initialize`. The test suite checks this with the official 1.x and 2.x clients.

## Concurrency

Each app starts its own server process; all of them share one SQLite database in WAL mode. Every check-then-write runs inside `BEGIN IMMEDIATE`, so claims and id allocation are atomic across processes. Proofs run in detached processes that write their result back to the database, so they survive the chat that started them.

## Data

`.roundtable/` holds `roundtable.db`, `config.toml`, `STATUS.md`, `logs/`, `proofs/`, `seats/<seat>/mcp.json` and `export/`. Everything is git-ignored. The event log is append-only; digests, the dashboard and exports are views of it.
