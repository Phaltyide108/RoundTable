# Roundtable

Let several AI models plan, build and review one project together, and ask them anything as a council. For example, Claude in Claude Code, GPT in Codex and a free model in opencode.

No API keys: every model runs in the app you already use, on your normal plan. Roundtable is the shared table they sit at: a desktop app and a small local program that keep the plan, the tasks, who may edit which files, the reviews and the alerts. Models never talk to each other directly. They read and write that shared record through MCP, the standard way AI apps connect to tools.

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

- **Smarter together.** Ask the table a question and every AI answers on its own; they rank each other's answers without knowing who wrote which, and the best one writes the final answer, fixing what the others caught. When a task fails twice, a model from another company diagnoses it by itself.
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

The installer adds **Roundtable to your app menu** (Launchpad on macOS, the Start menu on Windows): open it like any other app. If it didn't, run `rt app --install`.

Check it: `rt --version`. If your system already has a different `rt` program, use `roundtable` instead: every command works with either name. Upgrade later with `pipx upgrade roundtable-ai` or `uv tool upgrade roundtable-ai`.

## Quickstart: the app

Open **Roundtable** from your app menu (or run `rt app` in a terminal). It opens in a window of its own, not a browser tab. The first visit is four steps:

1. **Set up Roundtable in a folder**: **Browse…** to your project (a git repository with at least one commit). It only adds a hidden `.roundtable` folder.
2. **Choose your AIs**: tick the apps they run in (Claude Code or Codex in a terminal, Claude Code or Codex in VS Code, Gemini CLI, Qwen Code, opencode, Copilot CLI, Cursor, or the Claude / ChatGPT desktop apps). Names are filled in; the model box lists every model the app offers, free ones marked. Two from different companies catch each other's mistakes.
3. **Start them.** Easiest: **Run in the background**. Roundtable starts Claude Code, Codex or opencode by itself, with your own login, whenever that AI has work, and puts it back to sleep when it is done: nothing gets stuck waiting for you to type "check roundtable". Or open each one in a terminal (already connected) and watch it there. Editors open the right folder, and the app shows the one message to send.
4. **Give them a goal, or ask them something.** Choose **Plan together** (each AI writes a plan, they compare notes and agree) or **Just do it** (one AI splits your message into tasks at once, e.g. "sol: fix the usage numbers. opus: add a thinking setting"), how carefully they check each other (Light, Standard or Thorough), and whether to **start without asking you** to approve the plan. Or choose **Ask the table** to put a question to all of them.

Then you are in **the room**. Everything the AIs do arrives in the middle as a conversation, and while they work you see it live: their thinking, the commands they run and the files they edit. Whatever needs you (approving the plan, changes to check, work the AIs found, problems, tied votes, an AI that isn't started) is pinned just above the message box with the buttons that settle it; when nothing is pinned, you have nothing to do. Your AIs sit as small faces in the bar on top (a blue dot while one works); the plan opens from the bar, and anything else (an AI's usage, its model and how hard it thinks, everything it did, a task's tests and diff, settings, help) opens from the menu as a sheet over the conversation and closes with Esc. **Help** lists the terminal command for every button.

## Ask the table

Choose **Ask the table** in the message box, or in a terminal:

```bash
rt ask "Why does the login sometimes take ten seconds? Where would you fix it?"
```

1. Every AI answers on its own, in parallel. They can read your project and its git history, read-only.
2. Each one reads all the answers as Answer A, B, C (shuffled, no names) and says what is right and wrong in each, then ranks them, its own included.
3. The AI whose answer the others ranked best writes the final answer from every answer and review.

The conversation shows each AI's progress live; the question's panel shows every answer, every review and how they ranked each other. **Build this** turns the answer into a goal for the same AIs; **Ask a follow-up** keeps the context. This is [Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council), run with your own subscriptions instead of an API key, and with your code open to it.

The same council works by itself when building: a task that fails its tests twice in a row gets a diagnosis from a model of another company, sent to the builder as a suggestion it must answer.

## Does a team do better than one AI?

`rt bench run` finds out on your own computer. It gives the same written specification to each AI alone and to the team, then runs hidden tests none of them saw against what each one built, and writes a report: tests passed, minutes and tokens. Two tasks:

- `sheet`: a small spreadsheet engine (formulas, functions, errors, cycles), 52 hidden tests;
- `sql`: a small SQL engine that must answer exactly like SQLite (NULL logic, integer division, type affinity, ordering, GROUP BY, joins), 111 hidden tests that compare it with real SQLite.

```bash
rt bench run --task sql                        # Claude alone, Codex alone, then both as a team (45 min each at most)
rt bench run --solo claude:high --team claude:high,codex:xhigh --mode full
```

It uses your real Claude Code and Codex limits. Each contender's work is kept next to the report, and `rt bench score FOLDER --task sql` scores any folder against the hidden tests.

**What we measured (October 2026, Linux, default thinking):**

| Task | Claude Opus 5.5 alone | GPT-6.1 Sol alone | Team (both) |
| --- | --- | --- | --- |
| sheet (52 tests) | 52/52 in 6.5 min | 52/52 in 20.7 min | stopped: Claude's 5-hour limit ran out mid-run; the unmerged work passed 52/52 |
| sql (111 tests) | 111/111 in 27.9 min | 111/111 in 19 min | stopped: Claude's limit again (fixed since) |

And with small models at low thinking, where single models do make mistakes:

| Task | Claude Haiku 5.5 alone | GPT-6 Luna alone | Team (both) |
| --- | --- | --- | --- |
| sql (111 tests) | 111/111 in 4.7 min | 110/111 in 2.3 min | 111/111 in 9.7 min |
| pond, a three.js koi pond (25 checks) | 25/25 in 5 min | 14/25 in 1.4 min: its physics breaks | 25/25 in 6.4 min |

The honest reading so far: the team is as good as its best member and much better than its weakest; it has not yet beaten its best member, and it costs several times the tokens. On a clear specification of this size, today's top models each get everything right alone, so a team cannot be *more* accurate there; it costs more time and tokens, because the other model reviews the work. The first team run did find what a team is good for: when one AI ran out of its plan's usage, its work could pass to the other (which Roundtable now does by itself, keeping the work done so far), and the reviewer found real issues the hidden tests didn't cover. Where teams should help most is where a single model makes mistakes: smaller models, vaguer goals, bigger codebases. [docs/benchmarks.md](docs/benchmarks.md) has every run and its details.

## Quickstart: the terminal

The same, without the app:

```bash
rt init
rt seat add opus --model claude-opus-5-5 --app claude-code
rt seat add sol  --model gpt-6.1-sol     --app codex-cli
rt run opus --detach        # Roundtable runs it in the background whenever it has work
rt run sol --detach         # (or: rt launch sol, a terminal you watch and talk to)
rt goal "Add a REST endpoint for user profiles, with tests" --review mid   # --quick: skip the planning rounds
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
| opencode (75+ models, some free) | `opencode` | **Run in the background**, or Start / `rt launch` | yes (per-seat `opencode.json`) |
| GitHub Copilot CLI | `copilot-cli` | Start / `rt launch`; `rt setup copilot` once | send "join Roundtable as …" |
| Cursor | `cursor` | Start opens the folder in Cursor | yes (per-seat `.cursor/mcp.json`) |
| Claude desktop app | `claude-app` | `rt setup claude-app` once, new chat | send "join Roundtable as …"; plans and reviews only |
| ChatGPT desktop app, Codex mode | `codex-app` | `rt setup codex` once, open the folder | send "join Roundtable as …" |
| Anything else with MCP | `other` | add the server by hand (the AI's panel shows what to enter) | send "join Roundtable as …" |

Per-seat settings files are written into that model's working copy and hidden from git (`.git/info/exclude`), so they never show up as changes. Claude Code and Codex are verified end to end with the real apps; opencode's event stream and model list were read from the real app, its background runs tested with a stand-in; the other apps' settings formats follow their current documentation.

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
- **Search and filters.** `rt task list --status backlog --kind bug --label auth --priority 1`, and full-text search on the History page.

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

Numbers that are out of date say so, and a 5-hour or weekly window that has reset since is shown as reset, never as its old percentage. Where the numbers come from: Claude Code seats started with `rt launch` get a status line that shows their usage and inbox, and passes the numbers to Roundtable. Plan limits appear on Pro and Max plans. Codex seats are read from Codex's own session logs. The desktop chat apps don't share these numbers, so only Roundtable's cost is shown for them. `rt watch` notifies you when a seat passes 90% of a limit (`rt config set usage.warn_percent 80` to change it). Seats from the same company usually share one plan's limits.

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

- Only Claude Code, Codex and opencode can run in the background or answer questions to the table (Roundtable starts them headless with `claude -p`, `codex exec` and `opencode run`). Chat panels, editors and desktop apps act only while you talk to them: `rt watch` notifies you and you say "check roundtable" in that chat.
- An AI running in the background may, by default, edit files in its own working copy, use git and run the project's test commands; anything else is refused. `rt config set runner.permissions all` lets it run any command in its working copy.
- One computer: all models must run on the machine that holds the project (no sync across computers yet).
- Seats on the same subscription share its usage limit.
- ChatGPT's plain Chat mode isn't supported: it reaches custom MCP servers only through Developer Mode and a public tunnel.
- Roundtable is built for a few models working closely (2–6 seats), not dozens in parallel.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Anything odd | `rt doctor` checks everything and prints the fix for each problem |
| "seat X is live in another chat" | if that chat is closed: `rt seat release X` |
| Nothing happens after you give a goal | the AIs aren't running: the room says so; choose **Run them in the background** (or `rt run opus --detach`) |
| `rt app` opens a browser tab instead of a window | no window toolkit found: install Chrome, Edge, Brave or Chromium (Linux: or `python3-gi` with WebKitGTK); `rt doctor` says which one it uses |
| An AI running in the background is "stuck" | its panel shows why (often: not signed in to the app on this computer); sign in once with `claude` or `codex`, then **Try again now** |
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

## Compared with LLM Council, Beads, Gas Town and MCP Agent Mail

Roundtable runs LLM Council's method (independent answers, anonymous ranking, a chairman) with your own subscriptions and your code open to it, and turns the answer into work. It covers Beads' tracking basics (priorities, kinds, labels, epics, links, discovered work, memory, compaction) and adds what none of them have: models from different companies planning blind and critiquing each other anonymously, tests run by Roundtable itself before anything closes, enforced file barriers with per-model working copies, review depth you choose, severity 1–5 alerts that can stop work, desktop chat apps as members, a usage view per model, and a full dashboard. Still missing: syncing one table across several computers (Beads uses Dolt for that), workflow templates, pull-request based merging, and the scale of Gas Town (20–50 agents). The full list is in [docs/comparison.md](docs/comparison.md).

## Credits and inspiration

- Planning together and asking the table follow [Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council): models answer independently, review each other's answers anonymously, and a chairman merges the result. Roundtable applies that to questions, plans and code, with you as the final vote.
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
- [Benchmarks](docs/benchmarks.md): every `rt bench` run, its numbers and what we learned
- [First real run](docs/first-real-run.md): Claude and GPT build two features of Roundtable itself, step by step
- [Comparison with LLM Council, Beads, Gas Town and MCP Agent Mail](docs/comparison.md): what we lack, what we add

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports: please include the output of `rt doctor`.

## License

MIT. See [LICENSE](LICENSE).
