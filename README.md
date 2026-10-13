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
- At least two AI apps from the table below, signed in with your own plans (no API keys)
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

## Quickstart: the dashboard

In your project's main folder (a git repository with at least one commit):

```bash
rt ui
```

Your browser opens the dashboard. Everything is a button from there:

1. **Set up Roundtable in this folder** (it only adds a hidden `.roundtable` folder).
2. **Models → Add a model**, two or more, ideally from different companies. Pick where each runs: Claude Code or Codex in a terminal, Claude Code or Codex in VS Code, Gemini CLI, Qwen Code, opencode, Copilot CLI, Cursor, or the Claude / ChatGPT desktop apps.
3. **Start** each one. Terminal apps open in a new terminal window in the model's own working copy, already joined. Editors open the right folder, and the page shows the one message to send.
4. **Plan → Start a plan**: write the goal and choose the review depth.
5. When the models agree, **Overview** shows "The plan is ready for you". Read the tasks and the test commands they will run, tick the box, **Lock the plan**.
6. Watch work move on the Overview: who is doing what at the table, what needs you, tests, reviews and merges. The **Guide** page explains every word and lists the terminal command for every button.

## Quickstart: the terminal

The same, without the browser:

```bash
rt init
rt seat add opus --model claude-opus-5-5 --app claude-code
rt seat add sol  --model gpt-6.1-sol     --app codex-cli
rt launch opus              # in one terminal
rt launch sol               # in another
rt goal "Add a REST endpoint for user profiles, with tests" --review mid
rt status                   # what needs you
rt plan view && rt plan lock
```

Plain `rt` tells you the next step; `rt --help` groups the commands by purpose.

## Apps that can sit at the table

| App | `--app` | How it starts | Knows which model it is |
| --- | --- | --- | --- |
| Claude Code in a terminal | `claude-code` | Start / `rt launch` | yes, with a usage status line |
| Codex CLI | `codex-cli` | Start / `rt launch` | yes |
| Claude Code in VS Code | `claude-vscode` | Start opens the folder in VS Code | yes (per-seat `.mcp.json`) |
| Codex in VS Code | `codex-vscode` | Start opens VS Code; `rt setup codex` once | send "join Roundtable as sol" |
| Gemini CLI | `gemini-cli` | Start / `rt launch` | yes (per-seat `.gemini/settings.json`) |
| Qwen Code | `qwen-code` | Start / `rt launch` | yes (per-seat `.qwen/settings.json`) |
| opencode | `opencode` | Start / `rt launch` | yes (per-seat `opencode.json`) |
| GitHub Copilot CLI | `copilot-cli` | Start / `rt launch`; `rt setup copilot` once | send "join Roundtable as …" |
| Cursor | `cursor` | Start opens the folder in Cursor | yes (per-seat `.cursor/mcp.json`) |
| Claude desktop app | `claude-app` | `rt setup claude-app` once, new chat | send "join Roundtable as …"; plans and reviews only |
| ChatGPT desktop app, Codex mode | `codex-app` | `rt setup codex` once, open the folder | send "join Roundtable as …" |
| Anything else with MCP | `other` | add the server by hand (the Models page shows what to enter) | send "join Roundtable as …" |

Per-seat settings files are written into that model's working copy and hidden from git (`.git/info/exclude`), so they never show up as changes. Claude Code and Codex are verified end to end; the other apps' settings formats follow their current documentation.

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

## Tracking work (what Beads does, and more)

- **Kinds, priorities, labels.** Tasks are `task`, `feature`, `bug`, `chore`, `docs`, `test` or `epic`, with priority P0 (urgent) to P4 (someday) and labels. Ready work is handed out most urgent first.
- **Epics.** Group tasks under an epic; it finishes when its tasks do.
- **Links.** `waits_for` (a real dependency), `related`, `discovered_from`, and `parent`.
- **Discovered work.** A model that finds a bug outside its task files it (`rt_task file`) instead of fixing it on the side or forgetting it. It lands in your backlog; you accept it with its files and test command in one click (`rt task accept T9`).
- **Project memory.** `rt memory add "tests need DATABASE_URL"`, or a model's `rt_memory add`. Every model sees the pinned notes and the newest others when it joins, so a fresh chat starts with what earlier chats learned. Notes from models are shown to other models as data, not instructions.
- **Compaction.** `rt compact` keeps each finished task's outcome and drops the step-by-step detail of work finished more than 30 days ago.
- **Search and filters.** `rt task list --status backlog --kind bug --label auth --priority 1`, and full-text search of the history on the Activity page.

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

- Models don't listen in the background. Command-line models can be woken for critical alerts; chat panels and desktop apps can't, so `rt watch` notifies you and you say "check roundtable" in that chat.
- One computer: all models must run on the machine that holds the project (no sync across computers yet).
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

## Light and fast

Measured on Linux with Python 3.13 (October 2026):

| | |
| --- | --- |
| Package | 188 KB wheel, no third-party dependencies (only `tomli` on Python 3.10) |
| MCP server start | about 80 ms |
| A typical model call (`rt_sync`) | about 3 ms median, 4 ms at p95 |
| Memory per connected model | about 22 MB |
| Tool definitions | about 2,900 tokens, once per chat session |
| Catching up | a digest of only what changed for that model, built by plain code (0 model tokens) |

One SQLite file holds everything; no server or daemon has to run. A Go binary such as Beads starts faster per command than Python does, so `rt` commands from the terminal take about 0.1 s.

## Compared with Beads, Gas Town and MCP Agent Mail

Roundtable now covers Beads' tracking basics (priorities, kinds, labels, epics, links, discovered work, memory, compaction) and adds what none of them have: models from different companies planning blind and critiquing each other anonymously, tests run by Roundtable itself before anything closes, enforced file barriers with per-model working copies, review depth you choose, severity 1–5 alerts that can stop work, desktop chat apps as members, a usage view per model, and a full dashboard. Still missing: syncing one table across several computers (Beads uses Dolt for that), workflow templates, pull-request based merging, and the scale of Gas Town (20–50 agents). The full list is in [docs/comparison.md](docs/comparison.md).

## Credits and inspiration

- Planning together follows [Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council): models answer independently, review each other's answers anonymously, and a chairman merges the result. Roundtable applies that to plans and code, with you as the final vote.
- Tracking ideas come from Steve Yegge's [Beads](https://github.com/steveyegge/beads) and Gas Town; messaging ideas from [MCP Agent Mail](https://github.com/Dicklesworthstone/mcp_agent_mail).
- The dashboard follows the design rules of [Impeccable](https://impeccable.style/).

## Documentation

- [Guide](docs/guide.md): every dashboard page and its terminal command, in plain words
- [Concepts](docs/concepts.md): seats, plans, tasks, leases, proofs, reviews, alerts, votes
- [Setting up apps](docs/setup-apps.md)
- [Command reference](docs/cli.md)
- [MCP tools reference](docs/mcp-tools.md), for writing prompts
- [Edge cases](docs/edge-cases.md)
- [Architecture](docs/architecture.md), for contributors
- [First real run](docs/first-real-run.md): Claude and GPT build two features of Roundtable itself, step by step
- [Comparison with Beads, Gas Town and MCP Agent Mail](docs/comparison.md): what we lack, what we add

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports: please include the output of `rt doctor`.

## License

MIT. See [LICENSE](LICENSE).
