# Changelog

## 0.1.0 (2026-10-13)

First release.

- Seats: any number of models from any companies, each in its own chat; join keys; one live chat per seat.
- Planning: blind drafts, anonymous critique with cross-company coverage, chair merge, approvals, one revision round, votes, human lock that lists every test command.
- Tasks: dependency graph, atomic claims, per-task git branches in per-seat working copies, checkpoints with short summaries.
- File leases with expiry, and a git pre-commit guard that never breaks your own commits.
- Proof-to-close: Roundtable runs each task's test command in a detached background process, with time limits and output caps.
- Review depth low / mid / high with cross-company reviewer choice, hunk maps, spot checks, line comments and estimated token costs.
- Suggestions that must be answered, alerts at severity 1-5 (holds, freezes, STOP), votes with reasons.
- Per-seat digests built from an event log at zero model-token cost.
- Dependency-free MCP server (stdio), tested with the official MCP client 1.30.0 and 2.x and with Claude Code 2.1.296.
- `rt usage`: per-seat context size, session tokens, 5-hour and 7-day plan limits (from Claude Code's status line and Codex session logs), plus the token cost of the exchange between models. Claude Code seats launched with `rt launch` show it in their status line; `rt watch` warns near a limit.
- `commit=true` on `rt_task checkpoint` / `close`: Roundtable commits the seat's leased files itself, with the seat as author. Needed for Codex, whose sandbox keeps `.git` read-only.
- Proof runs no longer inherit `RT_SEAT` / `RT_HOME`, so a project's own tests never act as the seat.
- `AGENTS.md` / `CLAUDE.md` for models working on this repository, and docs/first-real-run.md.
- Install script that needs no sudo (uses uv or pipx, installs uv if neither exists).
- `rt` command line, `rt setup` for Claude Code / Claude app / Codex (merged with backups), `rt launch`, `rt doctor`, `rt watch` (notifications and wake-ups), `rt ui` local dashboard.
