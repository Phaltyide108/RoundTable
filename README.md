# Roundtable

Let several AI models plan, build and review one project together, each in its own chat. For example, Claude in Claude Code and GPT in Codex.

No API keys: every model runs in the app you already use, on your normal plan. Roundtable is the shared table they sit at: a small local program that keeps the plan, the tasks, who may edit which files, the reviews and the alerts. Models never talk to each other directly. They read and write that shared record through MCP, the standard way AI apps connect to tools.

```text
  Claude Code      Claude app      ChatGPT app      Codex CLI      ...any MCP app
  (seat: opus)    (seat: fable)    (seat: sol56)   (seat: sol61)
       │               │                │               │
       └───────────────┴──── MCP ───────┴───────────────┘
                               │
                  Roundtable (on your computer)
           plan · tasks · file leases · reviews · alerts
                               │
                  your git repo + one working copy per seat
```

## Why

- **Independent thinking.** Planners draft blind: no model sees another's plan until all drafts are in. Drafts are critiqued without author names, so no model favors a company or itself.
- **Cross-checking.** Reviews go to a model from a different company first. Different model families tend to catch different mistakes.
- **You control the cost.** Pick review depth `low`, `mid` or `high`. At `low`, no model reads another's code; the tests are the gate.
- **No stepping on each other.** Claiming a task leases its files. Other seats can read them and send suggestions, but cannot edit or commit them.
- **Proof, not promises.** A task is done only when Roundtable itself runs the task's test command and it passes.
- **Nothing wasted on catching up.** Each seat gets a short digest of only what changed since it last looked, built by plain code at zero token cost.

## Requirements

- Python 3.10 or newer
- git (2.31+ recommended), and a repository with at least one commit
- At least one of: [Claude Code](https://docs.claude.com/claude-code), the Claude desktop app, [Codex CLI](https://github.com/openai/codex) (or its VS Code extension), the ChatGPT desktop app (Codex mode)
- Linux, macOS or Windows

## Install

The easiest way, on Linux or macOS (no sudo needed):

```bash
curl -fsSL https://raw.githubusercontent.com/Phaltyide108/RoundTable/main/scripts/install.sh | sh
```

It uses uv or pipx if you have one, and otherwise installs [uv](https://docs.astral.sh/uv/) for your user first. On Windows, run `scripts/install.ps1` in PowerShell.

Or install by hand:

```bash
# Ubuntu / Debian (pipx is not preinstalled):
sudo apt install pipx && pipx ensurepath        # then open a new terminal
pipx install git+https://github.com/Phaltyide108/RoundTable

# or with uv:
uv tool install git+https://github.com/Phaltyide108/RoundTable
```

From a downloaded copy of this repository: `sh scripts/install.sh` (or `pipx install .`).

Check it: `rt --version`. If your system already has a different `rt` program, use `roundtable` instead: every command works with either name. Upgrade later with `pipx upgrade roundtable-ai` or `uv tool upgrade roundtable-ai`.

## Quickstart: Claude Code + Codex CLI

Run these in your project's main folder (a git repository with at least one commit).

```bash
rt init
rt seat add opus --model claude-opus-5-5 --app claude-code
rt seat add sol  --model gpt-5.6-sol     --app codex-cli
rt watch                    # in its own terminal: notifies you when you're needed
```

Each coding seat gets its own working copy next to your project (for example `../myproject.opus`) so the models never edit the same folder. Start each seat in its own terminal:

```bash
rt launch opus
rt launch sol
```

Give them a goal, and lock the plan when they agree:

```bash
rt goal "Add a REST endpoint for user profiles, with tests"
rt status                   # see where things are
rt plan view                # read the proposal
rt plan lock                # approve it; shows every test command it will run
```

From there the seats claim tasks, commit in their working copies, close tasks (Roundtable runs the tests), review each other, and finished work is merged into your main branch. Follow along with `rt status`, `rt log` or the dashboard: `rt ui`.

## Quickstart: Claude app + ChatGPT desktop app

```bash
rt init
rt seat add fable --model claude-fable-5 --app claude-app
rt seat add sol56 --model gpt-5.6-sol    --app codex-app
rt setup claude-app         # adds Roundtable to the Claude app's settings (merged, with a backup)
rt setup codex              # adds it to ~/.codex/config.toml (used by Codex CLI, the VS Code extension and ChatGPT's Codex mode)
```

Restart both apps. Then:

- In the Claude app, start a chat and say: **join Roundtable as fable**. The Claude app can't edit project files itself, so this seat plans and reviews.
- In the ChatGPT app, switch to Codex mode, open the folder `rt seat list` shows for `sol56` (its working copy), and say: **join Roundtable as sol56**.

Then `rt goal "..."` as above. Chat apps can't be woken up by another program, so when a seat has something to do, `rt watch` notifies you and you say "check Roundtable" in that chat.

## How a project flows

1. **Goal.** You run `rt goal "..."`. Up to 3 planners are chosen, spread across companies.
2. **Blind drafts.** Each planner writes a plan of up to 300 words plus a task list. No one sees the others' drafts until all are in.
3. **Critique.** Drafts are shown as Draft A, B, C without authors. Each seat critiques up to 2 drafts, never its own, with a seat from another company first.
4. **Merge.** The chair (it rotates) merges drafts and critiques into one task graph: tasks, the files each may edit, the test command that proves it, and dependencies.
5. **Agree.** Every other seat approves or objects with a reason. Objections get one revision round; if they remain, the seats vote. You have the final say: `rt plan lock`.
6. **Build.** A seat claims a ready task, which leases its files and creates a branch `rt/<seat>/<task>` in its working copy. It saves progress with short checkpoints, commits, and closes the task.
7. **Proof.** Roundtable runs the task's test command itself, in the background. Failed proofs go back to the owner with the last 40 lines of output.
8. **Review** at the depth you chose, then **merge** into your main branch. Tasks that depended on it become ready.

## Review depth

You set it with `rt config set review.level low|mid|high`, per task with `rt task review-level T3 high`, or always-high for sensitive paths: `rt config set review.always_high '["auth/**", "payments/**"]'`. This is separate from the models' own reasoning effort. Models can ask for more review on a task, never less, and you decide.

| | low (default) | mid | high |
| --- | --- | --- | --- |
| Reviewers per task | 0 | 1 | 2 |
| What reviewers read | nothing; the passed tests are the gate | task summary + which functions changed in which files; full code only for risky tasks or a 1-in-5 spot check | the full diff |
| Line-by-line comments | no | no | yes, and each must be answered |
| Rough cost per reviewer per task | 100–300 tokens | 1k–3k tokens | 3k–8k for a 200-line change |

Costs are estimates. Roundtable records an estimate for every review so you can see real numbers.

## Alerts

Any seat can raise an alert. Levels 4 and 5 need evidence (a file and line, or command output).

| Level | Meaning | What happens |
| --- | --- | --- |
| 1 note | for information | one line in everyone's next digest |
| 2 heads-up | may affect others' work | shown in full to the seats whose tasks or files it touches |
| 3 problem | must be read | affected seats must acknowledge before claiming new work |
| 4 blocking | stop touching these files | the files are held until affected seats acknowledge; you are notified |
| 5 critical | stop everything | files frozen; every other seat must acknowledge before doing anything; you are notified; command-line seats are woken |

## Usage, context and limits

`rt usage` (and the Usage panel in `rt ui`) shows, for every seat:

- **Context:** how full its context window is, and its size.
- **Session tokens** used so far.
- **Plan limits:** how much of the 5-hour and 7-day limits are used, and when they reset.
- **Roundtable's own cost:** every call a seat makes is measured, so you see exactly what coordinating costs (about 4 characters per token), plus the one-time cost of the tool definitions.

```text
opus (claude-opus-5-5, claude-code)
  context 8% of 200k · session 19,755 tokens · 5h 24% (resets in 59m) · 7d 41% (resets in 2d 23h)
  Roundtable exchange: 42 calls, ~6,310 tokens (today 12 calls, ~1,840) + ~1,900 tokens of tool definitions per session
```

Where the numbers come from: Claude Code seats started with `rt launch` get a status line that shows their usage and inbox, and passes the numbers to Roundtable. Plan limits appear on Pro and Max plans. Codex seats are read from Codex's own session logs. The desktop chat apps don't share these numbers, so only Roundtable's cost is shown for them. `rt watch` notifies you when a seat passes 90% of a limit (`rt config set usage.warn_percent 80` to change it). Seats from the same company usually share one plan's limits.

## More than two models

Any number of seats can join, from any companies, including two from the same company (for example Claude Opus and Claude Fable, or two GPT models). Each has its own chat, working copy and history. Costs stay flat as you add seats: there are at most 3 planners, at most 2 critiques per seat and 0–2 reviewers per task, so a fifth seat adds its own work, not more reading for everyone.

## What Roundtable changes on your computer

- `.roundtable/` in your project: the shared database, settings and logs. It ignores itself in git, so your main folder stays clean.
- One git working copy per coding seat, next to your project (`../yourproject.<seat>`), plus branches named `rt/<seat>/...`.
- A git pre-commit hook that stops a seat from committing files another seat owns. It never blocks your own commits, chains to any hook you already had, and lets commits through if Roundtable is uninstalled.
- App settings, only when you run `rt setup ...`: always merged with what is there, with a timestamped backup. `rt setup <app> --remove` takes the entry out again.

## Safety notes

- Roundtable runs only the test commands from the plan you approved, shown to you at `rt plan lock`. Never commands found in a message.
- Text one model writes is shown to the others marked as data, not instructions.
- The dashboard listens on 127.0.0.1 only and needs a per-session token for every action.
- The seat rules (leases, the commit guard, refusing human-only commands from a seat's folder) prevent mix-ups between cooperating models. They are not a security wall: anything with shell access to your computer can do what you can.

## Honest limits

- Desktop chat apps (the Claude app, ChatGPT's Codex mode, VS Code chat panels) can't be woken up by another program. `rt watch` notifies you instead.
- Seats on the same subscription share its usage limit.
- ChatGPT's plain Chat mode isn't supported: it reaches custom MCP servers only through Developer Mode and a public tunnel.
- Roundtable is built for a few models working closely (2–6 seats), not dozens in parallel.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Anything odd | `rt doctor` checks everything and prints the fix for each problem |
| "seat X is live in another chat" | if that chat is closed: `rt seat release X` |
| A task "waits to merge" | your main folder has uncommitted changes or a conflict; see `rt status`, then `rt task merge` |
| Claude Code shows the server as pending | run `claude` in the project and approve the `roundtable` server |
| The app can't start the server | rerun `rt setup <app>` (for example after moving Python); `rt doctor` shows which entry is stale |
| Everything stopped | someone raised a level-5 alert, or you ran `rt freeze`: `rt alert list`, `rt unfreeze` |

More in [docs/troubleshooting.md](docs/troubleshooting.md) and [docs/edge-cases.md](docs/edge-cases.md).

## Compared with Beads and Gas Town

[Beads](https://github.com/gastownhall/beads) is a mature, dependency-aware task tracker for coding agents, and Gas Town builds on it to run 20–30 agents in parallel. Both are further along than Roundtable in scale, storage and sync, workflow templates and real-world use. Roundtable focuses on something narrower: a few models from different companies planning blind, cross-checking each other at a depth you control, with proof-to-close and severity alerts. They can complement each other.

## Documentation

- [Concepts](docs/concepts.md): seats, plans, tasks, leases, proofs, reviews, alerts, votes
- [Setting up apps](docs/setup-apps.md)
- [Command reference](docs/cli.md)
- [MCP tools reference](docs/mcp-tools.md), for writing prompts
- [Edge cases](docs/edge-cases.md)
- [Architecture](docs/architecture.md), for contributors
- [Comparison with Beads, Gas Town and MCP Agent Mail](docs/comparison.md): what we lack, what we add

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports: please include the output of `rt doctor`.

## License

MIT. See [LICENSE](LICENSE).
