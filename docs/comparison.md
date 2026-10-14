# How Roundtable compares

An honest, feature-by-feature list of what other open-source tools do that Roundtable does **not** do (yet), followed by what Roundtable does that they don't. Checked against public docs in October 2026; these projects move fast, so verify before relying on a line here.

- **LLM Council** (karpathy/llm-council): several models answer a question, rank each other's answers anonymously, and a chairman writes the final answer.
- **Beads** (steveyegge/beads): a dependency-aware issue tracker for coding agents.
- **Gas Town** (steveyegge/gastown): a manager that runs and supervises many coding-agent sessions.
- **MCP Agent Mail** (Dicklesworthstone/mcp_agent_mail): email-like messaging and file reservations between agents.

Legend: **Gap** = they have it, we don't. **Partial** = we have a smaller version.

## Compared with LLM Council

| Feature | LLM Council | Roundtable |
|---|---|---|
| Independent answers, anonymous peer ranking, a chairman | Yes | **Yes** (0.4): "Ask the table" / `rt ask`. Answers are shown to the rankers as Answer A, B, C in random order; the aggregate ranking is shown; the chair is the AI whose answer ranked best (or each in turn). |
| How models are reached | OpenRouter API key, paid per token | **Your own subscriptions**: Claude Code, Codex and opencode run on this computer, no API keys. opencode's free models work too. |
| Models can read your code | No (a chat over a prompt) | **Yes**, read-only: every answer, ranking and final answer can open files and git history in your project, and must change nothing. |
| What happens next | The answer | "Build this" turns the agreed answer into a goal the same AIs plan, build, test and review; "Ask a follow-up" keeps the context. |
| Councils that happen by themselves | No | **Yes**: when a task fails its tests twice, another company's AI diagnoses it and the builder must answer. |
| Conversation history and stage tabs | Yes | **Yes**: every question, every answer, every review and the ranking table are kept per project. |
| Streaming each answer as it is written | Yes | **Partial**: each AI's live steps (reading, thinking) show while it answers; the text appears when the answer is done. |
| Any model on OpenRouter | Yes | **Partial**: what Claude Code, Codex and opencode offer (opencode alone lists 75+ models). |

## Compared with Beads

| Feature | Beads | Roundtable |
|---|---|---|
| Sync across machines | Version-controlled database (Dolt) with push/pull and federation | **Gap.** One SQLite file on one computer. All models must run on the same machine. |
| Collision-free IDs across branches/machines | Hash IDs | **Gap** (only matters once multi-machine exists). Sequential `T1`, `T2`. |
| Dependency kinds | blocks, parent-child, related, duplicates, supersedes, discovered-from | **Yes** (0.2): waits_for, related, discovered_from, parent (epics). No duplicates/supersedes yet. |
| Types, priorities, labels | Yes | **Yes** (0.2): task, feature, bug, chore, docs, test, epic; P0-P4; labels; ready work ordered by priority. |
| Agents file work they discover | Yes | **Yes** (0.2): `rt_task file` puts it in a backlog; the human accepts it with files and a test command. Duplicates are detected. |
| Long-term memory (`bd remember` / `bd prime`) | Yes | **Yes** (0.2): `rt memory` / `rt_memory`; pinned and recent notes are given to every model when it joins, marked as data when a model wrote them. |
| Compaction of old work | Semantic summaries of closed issues | **Partial** (0.2): `rt compact` drops step-by-step detail of old finished work and keeps outcomes. No model-written summaries. |
| Reusable workflow templates (formulas, molecules) | Yes | **Gap.** Every plan is written fresh. |
| Gates (timer, GitHub CI, human) | Yes | **Partial.** Human plan lock and proof-to-close; no timer or CI gates. |
| Setup for many agents | Claude Code, Codex, Cursor, Factory, mux and more | **Yes** (0.2): Claude Code (terminal and VS Code), Codex (terminal, VS Code, ChatGPT app), Gemini CLI, Qwen Code, opencode, Copilot CLI, Cursor, Claude desktop app, any MCP app. |
| JSON output | `--json` | **Yes**: `--json` on every command. |
| HTTP server for remote use | Experimental | **Gap** (stdio only, by design for now). |
| Web UI | Community tools | **Yes**: a desktop app (`rt app`, in your app menu) covers every human action. |
| Maturity | Large user base, many releases | **Gap.** Version 0.4. |

## Compared with Gas Town

| Feature | Gas Town | Roundtable |
|---|---|---|
| Starts and supervises agent sessions | Yes, in tmux, restarts them | **Yes for three apps** (0.3-0.4): background runs start Claude Code, Codex and opencode whenever a seat has work, resume their sessions, back off when stuck and stop at a time limit. Other apps: `rt launch` opens a terminal. The runners themselves don't restart after a reboot. |
| Scale | Built for 20-50 agents | Built for 2-6 seats. More works, but planning rounds get long. |
| Work survives a crashed agent | Hooks + crash recovery | **Partial.** Claims, checkpoints and leases persist; the seat sees them after `rt_sync`, but someone has to start the chat again. |
| Watchdog for zombie or stalled agents | Three-tier watchdog, health states, auto-nudges | **Partial.** Background runs wake a seat whenever it has work and say why it is stuck; `rt watch` reports stuck tasks, dead proof runs and expired leases. |
| Merge queue | Bisecting merge queue, GitHub/Bitbucket PRs | **Gap.** A proven task branch is merged locally with `--no-ff`. No pull requests, no queue, no bisect. |
| Usage-aware scheduling | Capacity governor, rotates across accounts | **Partial.** `rt usage` shows context, 5-hour and 7-day limits per seat and warns near limits; it does not slow down or switch accounts. |
| Find past sessions (Seance) | Yes | **Gap.** |
| Federation between teams, reputation | Yes | **Gap.** |
| Live activity feed | TUI | **Yes** (0.3): thinking, commands and edits of every AI, live in the app; `rt log` in the terminal. |
| Dashboard with actions | htmx dashboard, command palette | **Yes**: a desktop app with every human action, set-up screen, start models from it, guide built in. No command palette. |
| Telemetry, plugins, Docker image, shell completions, sandboxing | Yes | **Gap.** |

## Compared with MCP Agent Mail

| Feature | Agent Mail | Roundtable |
|---|---|---|
| Free-form messages with threads, To/Cc/Bcc, importance | Yes | **Partial.** Directed suggestions that must be answered, alerts with levels 1-5, and votes. No general chat threads or Cc. |
| Attachments and images in messages | Yes | **Gap.** Text only. |
| Full-text search of past messages | SQLite FTS5 | **Partial** (0.2): text search of the history on the dashboard's History page; `rt log` filters by time and task. |
| Shared vs exclusive file reservations | Both | **Partial.** Leases are exclusive; reading is always allowed, so "shared" is implied. |
| Contact policies (who may message whom) | Yes | Not needed: one project, every seat is a teammate. |
| Human can write to agents from the web UI | Overseer compose screen | **Partial** (0.2): raise alerts, file tasks, add memory and decide everything from the dashboard; no free-form message box. |
| Several projects linked together | Yes | **Gap.** One project per Roundtable. |
| Signed/encrypted static export, secret scrubbing | Yes | **Partial.** `rt export` writes a readable bundle; no signing, encryption or scrubbing. |
| Backups and repair | Doctor with repair, archives | **Partial.** `rt doctor` finds and explains problems; config writes are backed up; no database backup/restore command. |
| Network transport with auth and rate limits | HTTP + JWT/RBAC | **Gap** (by design for now): stdio only, join keys per seat, everything stays on your computer. |

## What Roundtable does that these don't

- **Asking the table, with your code open.** A council of models from different companies (your own subscriptions) that can read the project, ranks itself anonymously, and can turn its answer into work.
- **Second opinions that happen by themselves.** A task that fails twice gets a diagnosis from another company's model.
- **Planning together across companies.** Blind first drafts, anonymous critique arranged so each draft is checked by a different company's model, a rotating chair, approvals/objections, one revision round, then a human lock.
- **Review depth you choose: low / mid / high**, separate from the models' reasoning effort. Mid reviews a hunk map with spot checks; high gives two cross-company reviewers the full diff with line comments. Token cost is estimated before you raise it.
- **Proof-to-close.** A task cannot close on a ticked checkbox: Roundtable itself runs the test command in the background and records the result.
- **Barriers that are enforced, not requested.** File leases plus a git pre-commit guard in each seat's own working copy; you, the human, are never blocked.
- **Severity 1-5 alerts with teeth.** Level 3 must be acknowledged before new claims, level 4 holds files, level 5 freezes them and tells every seat to STOP.
- **"Since you last looked" digests** built from the event log at zero model-token cost.
- **Desktop chat apps as seats.** The Claude desktop app (and ChatGPT's Codex mode through Codex's config) can plan and review, not only CLIs.
- **Token accounting for the collaboration itself.** `rt usage` shows what the exchange between models cost, next to each model's own context and plan limits.
- **No API keys and no daemon required.** Each model uses its own subscription; `rt watch` is optional.
- **A benchmark you run yourself.** `rt bench` measures a team against each AI alone on hidden tests (a spreadsheet engine, and a SQL engine scored against real SQLite).

## Most valuable gaps to close next

1. Multi-machine sync, with hash IDs (so two computers can share one table).
2. Pull-request flow: open a PR per proven task instead of merging locally.
3. Automatic restart and nudging of stalled command-line models.
4. Plan templates (reusable workflows) and CI gates.
5. Duplicates/supersedes links and model-written summaries for compaction.
