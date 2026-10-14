# How Roundtable works

This explains what Roundtable is made of, what happens at each step of a project, and how it behaves when things go wrong. It is written for anyone who wants to understand the system, not only for contributors. The complete list of failure cases is in [edge-cases.md](edge-cases.md).

## 1. The big picture

Roundtable is a small program that runs on your computer. It is not a server in the cloud and it has no API keys. Each AI model keeps running in its own app (Claude Code, Codex, VS Code, a desktop app) on your own subscription. Roundtable is the shared record they all read and write: the plan, the tasks, who may edit which files, test results, reviews, alerts, votes and memory.

```text
 Claude Code      Codex        Gemini CLI     Claude app      You
 (seat opus)    (seat sol)    (seat gem)    (seat fable)       │
     │              │              │              │        browser / terminal
     │ MCP          │ MCP          │ MCP          │ MCP          │
 ┌───┴────┐     ┌───┴────┐     ┌───┴────┐     ┌───┴────┐   ┌─────┴──────┐
 │ server │     │ server │     │ server │     │ server │   │ rt ui / rt │
 └───┬────┘     └───┬────┘     └───┬────┘     └───┬────┘   └─────┬──────┘
     └──────────────┴──────┬───────┴──────────────┴──────────────┘
                           │  every action: dispatch.call(op, params, who)
                 ┌─────────┴──────────┐
                 │  .roundtable/      │   one SQLite database (+ config, logs)
                 │  roundtable.db     │
                 └─────────┬──────────┘
                           │  git: branches, diffs, merges, commit guard
          your project ────┼──── project.opus ──── project.sol ──── ...
          (main branch)        (working copies, one per coding model)
```

Three ideas carry the whole design:

1. **Models never talk to each other directly.** Each one only calls Roundtable's tools. What others did reaches it as a short digest. This keeps every model's context small and stops one model's text from steering another.
2. **Every action goes through one function.** The model tools (MCP), the `rt` command and the dashboard all call `dispatch.call`, which checks who is acting, applies the rules, runs the operation and records an event. Three front ends, one set of rules.
3. **Roundtable checks; it does not trust.** A model saying "done" is not enough: Roundtable runs the tests itself. A model promising not to touch a file is not enough: git refuses the commit. Claims, leases and merges are database transactions, not conventions.

## 2. What is on disk

| Where | What | Why |
| --- | --- | --- |
| `yourproject/.roundtable/roundtable.db` | The database: seats, plans, drafts, critiques, tasks, links, leases, proofs, reviews, alerts, votes, memory, events, usage | One file that every process shares |
| `.roundtable/config.toml` | Your settings, with a comment for each one | Readable and editable; validated on load |
| `.roundtable/logs/` | `mcp.log` (connections), `errors.log` (bugs), `notifications.log` | So nothing fails silently |
| `.roundtable/seats/<seat>/mcp.json` | The connection file `rt launch` gives Claude Code, bound to that seat | The app knows which model it is without a join step |
| `.roundtable/usage/<seat>.json` | Latest usage numbers from Claude Code's status line | Shown in `rt usage` and the dashboard |
| `.roundtable/.gitignore` containing `*` | Hides all of the above from git | Your main folder stays clean, so merges are never blocked by Roundtable's own files |
| `../yourproject.<seat>/` | One git working copy per coding model, on branches `rt/<seat>/...` | Models never edit the same folder, and never yours |
| `.git/hooks/pre-commit` | The commit guard (chained to any hook you already had) | Enforces file leases at commit time |
| `.git/info/exclude` | Hides per-seat settings files (`.mcp.json`, `.gemini/settings.json`, ...) | They never appear as changes |
| `~/.codex/config.toml`, Claude app config, `~/.copilot/mcp-config.json` | One Roundtable entry, only when you run `rt setup` | Merged with what is there, with a backup |
| `~/.config/roundtable/recent.json` | Projects you opened in the dashboard | The dashboard's project switcher |

## 3. The code

Plain Python, standard library only (plus `tomli` on Python 3.10). About 9,400 lines of Python and one hand-written web page.

| Layer | Modules | What they do |
| --- | --- | --- |
| Front ends | `mcp_server.py`, `cli.py`, `dashboard.py` + `ui/` | Turn a model's tool call, a terminal command or a button click into `dispatch.call` |
| Core | `dispatch.py`, `registry.py`, `context.py`, `errors.py` | Identity, permission, STOP checks, parameter validation, the inbox line, error handling, usage metering |
| Storage | `db.py`, `schema.py`, `config.py`, `paths.py` | SQLite with transactions and migrations; validated settings; finding the project |
| Collaboration | `seats.py`, `plans.py`, `tasks.py`, `leases.py`, `reviews.py`, `suggestions.py`, `alerts.py`, `votes.py`, `memory.py` | The rules of the table |
| Reading | `sync.py`, `inbox.py`, `report.py`, `ui_state.py`, `events.py`, `usage.py` | Digests, the one-line inbox, status, dashboard data, the event log, usage numbers |
| Git and tests | `gitops.py`, `guard.py`, `proofs.py`, `proofrun.py` | Working copies, branches, diffs, merges, the commit guard, running test commands |
| Your computer | `appsetup.py`, `launch.py`, `apps.py`, `desktop.py`, `doctor.py`, `watch.py`, `notify.py` | Connecting apps, starting models, opening terminals and editors, health checks, timing and notifications |

Each operation (`task.claim`, `plan.lock`, ...) is a plain function registered with `@op`. The registration says who may call it (a model, you, or either), its parameters, and which model tool it belongs to. The MCP tool list and the `rt` help are generated from these registrations, so the three front ends cannot drift apart.

## 4. One action, end to end

What happens when Claude calls `rt_task claim task="T3"`:

1. **The app sends it over MCP.** Each app starts its own copy of `python -m roundtable_ai mcp` and talks to it over stdin/stdout (JSON-RPC, one message per line). The server speaks MCP versions 2024-11-05 to 2025-11-25; newer clients that probe with `server/discover` are told "method not found" and fall back to the standard handshake.
2. **Who is calling?** A model started with `rt launch` (or opened in its own folder) is bound to its seat by an environment variable. Other chats join once with `rt_sync join="opus"` and get a short key they pass on every call, so two chats in one desktop app can never act as each other. A model's tool cannot call human-only operations, and the human cannot accidentally act as a model.
3. **Housekeeping.** Expired file leases are released and the caller's own leases are renewed.
4. **STOP checks.** If you pressed Stop all models (`rt freeze`), or a level-5 alert is waiting for this model's acknowledgement, the call is refused with STOP and the reason. Read-only calls still work.
5. **Parameters are checked** against the registration: types, required values, allowed choices.
6. **The operation runs inside a database transaction** (`BEGIN IMMEDIATE`). For a claim: is the task ready, is it this model's or unowned, has the model read the updates meant for it, are there alerts it must acknowledge first? If so, lease the task's files, mark it claimed, and record one event.
7. **Git.** Outside the transaction, switch the model's working copy to a branch `rt/opus/T3`. If that fails, the claim is undone: nothing is left half-done.
8. **The reply** starts with a one-line inbox (for example `[rt: 2 new · A2 L3 needs your ack · 1 review for you]`), so a model notices new work without asking.
9. **Metering.** The size of the request and reply is recorded, which is how `rt usage` knows what coordination costs.
10. **Errors** are explained, never raw: every expected failure is an `RTError` with what happened and the exact next step. An unexpected bug is written to `errors.log` and the model gets a clear message; its session keeps working.

## 5. The life of a project

### Setting up

`rt init` (or **Set up** in the dashboard) checks the folder: a git repository at its top level, not a model's working copy, with at least one commit. It creates `.roundtable/` and the database and changes nothing else. Without git, Roundtable runs in shared-folder mode: leases are still enforced, but there are no separate working copies, diffs or merges.

### Adding and starting models

Adding a model records its name, model, company (guessed from the app or model name) and roles (plan, build, review). A coding model gets its own git working copy next to your project, resting on a branch `rt/<seat>/idle`, and the commit guard is installed. For apps that read a settings file from their folder (Claude Code in VS Code, Gemini CLI, Qwen Code, opencode, Cursor), Roundtable writes one into that working copy, bound to the seat, and hides it from git.

Starting a model (**Start**, or `rt launch`) runs the app in its working copy. Claude Code gets the model name, the seat-bound connection file, a short system note and a status line that reports usage; Codex gets the same through `-c` settings. From the dashboard, Roundtable opens a new terminal window for this (GNOME Terminal, Ptyxis, Konsole, xfce, kitty, Alacritty, WezTerm, foot, xterm, macOS Terminal or a Windows console), or opens VS Code or Cursor on the right folder.

### Planning together

```text
goal ─> drafting ─> critique ─> merging ─> proposed ─> awaiting you ─> locked ─> done
           │            │           │          │  objection
           │ blind      │ A, B, C   │ chair    └─> one revision ─> vote if still split
```

1. **Goal.** You give the goal and the review depth. Up to three planners are picked, spread across companies.
2. **Blind drafts.** Each planner writes a plan of up to 300 words and a task list. A draft cannot see the others until all are in. Each task names the files it may change and the test command that proves it works, and can have a kind, priority, labels, an epic and dependencies. Cycles, unknown dependencies, paths outside the project and tasks without a test command are refused when submitted.
3. **Anonymous critique.** Drafts are relabelled A, B, C. Each model critiques up to two drafts, never its own, preferring a different company's (keep, change or drop, with reasons).
4. **Merge.** A chair, rotating between plans, merges the drafts and critiques into one task list.
5. **Agree.** Every other model approves, or objects with a reason. An objection gets one revision; if objections remain, the models vote.
6. **You lock it.** Locking shows every test command the plan will run on your computer. Nothing runs before you lock. After locking, models can propose amendments (add a task, change files, ...), which other models or you must approve.

This is the structure of Andrej Karpathy's LLM Council (independent answers, anonymous peer review, a chairman), applied to plans, with you as the final vote.

### Building

```text
backlog ─(you accept)─> open ─(dependencies done)─> ready ─(claim)─> claimed ─(close)─> proving
                                                                          ^                 │
                                                       tests failed ──────┘                 │ tests passed
                                                                                            v
                done <─(merged)─ merge_blocked <─(cannot merge yet)─ in_review ─(approved)─┘
                                                                     │
                                         changes_requested <─────────┘ (reviewer asks for changes)
```

- **Claim.** The model's working copy switches to the task's branch and the task's files are leased to it. Others can read them and send suggestions, which the owner must answer before closing.
- **Leases** last while the model is active and expire after 30 minutes of silence, so a crashed chat cannot hold files forever. A model can ask for more files; if another model holds them, it must send a suggestion instead.
- **The commit guard** (a git pre-commit hook in each working copy) refuses a commit that touches files the model does not lease, or files held by an alert. It only blocks on its own exit code, so your own commits and any hook you already had are never broken.
- **Checkpoints** are short progress notes (80 words) that others read instead of the code.
- **Close.** Roundtable checks that everything is committed and that every changed file is leased to the model. For apps whose sandbox cannot write to `.git` (Codex), `commit=true` lets Roundtable make the commit itself, with only the leased files and the model as author.
- **Proof.** Roundtable starts the task's test command in a separate background process in the model's working copy, with a time limit (15 minutes by default) that kills the whole process tree, and keeps the last 40 lines of output. If the runner itself dies (reboot, crash), that is detected and the task goes back to its owner. A failing test sends the task back with the output.
- **Review**, at the depth you chose: none at low; at mid one reviewer from another company reads a map of the changed functions, plus the full code for risky tasks and one task in five; at high two reviewers read the full diff and leave line comments that must be answered. A model can ask for a deeper review; you decide. Three rounds without agreement go to a vote. If no other model can review, it comes to you.
- **Merge.** The approved commit is merged into your main branch with `--no-ff`, only if your main folder is clean and on that branch. Otherwise the task waits as "waiting to merge" and Roundtable retries; your files are never touched. A conflict is aborted cleanly and the owner gets a level-3 alert. Tasks that waited on this one become ready, and an epic finishes when all its tasks have.

### Found work, memory and history

- A model that notices a bug outside its task **files** it (`rt_task file`). It goes to the backlog, linked to the task it was found in, and duplicates are caught by title. You accept it with its files and test command, or cancel it.
- **Project memory** is a set of short notes. Your notes are pinned; notes from models are shown to other models marked as data. When a model joins, it gets the pinned notes and the newest others with its rules card, so a new chat starts informed.
- **Events.** Every change records one line in an append-only event log. Digests, the dashboard, `rt log`, notifications and exports are all views of it. `rt compact` drops step-by-step detail of work finished more than 30 days ago and keeps the outcomes.

### Problems and decisions

- **Alerts, levels 1 to 5.** 1 is a note; 2 is shown to models whose work it touches; 3 must be acknowledged by them before they take new work; 4 holds the affected files and notifies you; 5 freezes the files, makes every other model's next call return STOP until it acknowledges, notifies you, and wakes command-line models. Levels 4 and 5 need evidence. Models can suggest a different level; you decide.
- **Votes** settle stuck decisions; every ballot needs a reason, and a tie goes to you.
- **Stop all models** (`rt freeze`) makes every model's next call return STOP until you let them work again.

## 6. Keeping token use low

- **Digests, not transcripts.** `rt_sync` returns only what changed since that model last looked, in one line per change: full lines for what touches its tasks, files or alerts, one summary line per model for everything else. This is built by plain code and costs no model tokens.
- **Zoom levels.** Tasks have a one-line title, an 80-word summary and full detail. Models read the level they need.
- **Review depth decides how much code anyone reads.** At low, nobody reads anybody's code.
- **Fixed limits on planning:** at most 3 planners, 2 critiques per model, 300-word drafts. A fifth model adds its own work, not more reading for everyone.
- **Measured.** Every call's size is recorded, so `rt usage` shows exactly what coordination costs, next to each model's own context and plan limits. The tool definitions cost about 2,900 tokens once per chat.

## 7. The dashboard

`rt ui` starts a small web server inside the same Python process, on `127.0.0.1` only, and opens your browser.

- The page (`ui/index.html`, `app.css`, `app.js`) has no framework and no build step. Every three seconds it asks `/api/state` for the whole picture (built by `ui_state.py` with plain queries, no git commands) and redraws, keeping what you were typing.
- Buttons call `/api/action` with a Roundtable operation, which runs through the same `dispatch.call` as the terminal, acting as you. Setting up, opening another project, starting a model and connecting an app go through `/api/do`.
- **Safety:** it listens only on 127.0.0.1; it checks the `Host` header (so a malicious website cannot reach it by DNS tricks); every change needs a random token embedded in the page and a same-origin request; a strict content security policy blocks injected scripts; all text is inserted as text, never as HTML; models can never call the dashboard.
- The screen is one room: the event log rendered as a conversation in the middle (each event type turned into one plain sentence), the decisions waiting for you pinned above the message box, the team on the left and the plan on the right. Every other view is a panel over the room addressed by the URL (`#/task/T3`, `#/ai/opus`), so links and the back button work.
- Without a project in the current folder it shows the set-up screen, and it can switch between projects without restarting.

## 8. Time: who wakes whom

Models only act when their app sends them a message. Roundtable cannot type into a chat window, but it can start Claude Code and Codex itself:

- **Background runs** (`runner.py`, `rt run <seat>`, or **Run in the background** in the dashboard): one small process per seat checks the table every few seconds. When the seat has work (`runner.pending`: a draft, critique, merge or approval it owes, an unacknowledged alert, a review, its own task to finish or fix, a ready task it can claim, or a new note from you) it runs the app headless: `claude -p "<what to do>" --output-format stream-json --verbose --model ... --effort ... --resume <session> --permission-mode acceptEdits --allowedTools ...`, or `codex exec --json -m ... -c model_reasoning_effort=... -c sandbox_mode="workspace-write" [resume <thread>] "<what to do>"` (flags checked against Claude Code 2.1.299 and Codex CLI 0.162). It reads the event stream line by line (`activity.py` turns thinking, tool calls, commands, edits and errors into short steps for the dashboard), keeps the session id so the next run continues the same conversation, and writes a heartbeat to `.roundtable/runs/<seat>.json`.
- A run that leaves the table unchanged is not repeated at once: the wait doubles from 1 to 30 minutes and the seat is shown as stuck with the app's own error. Runs are stopped after `runner.max_minutes`; nothing runs while you have paused everyone or that seat; one runner per seat; environment variables of a Claude Code session that `rt ui` may have been started from are not passed on.
- For seats you opened yourself, `activity.py` reads Claude Code's transcript and Codex's session log for that seat's folder, so the dashboard shows their steps too.

- Every reply carries the inbox line, so active models notice new work on their next call.
- `rt watch` (optional) runs in the background: it expires leases, cleans up dead test runs, retries waiting merges, refreshes `STATUS.md`, and sends you a desktop notification once per thing that needs you (a plan to lock, an alert at level 4 or 5, a tied vote, stuck work, a model near its usage limit).
- For a level-5 alert it can start a short background run of a command-line model (Claude Code with `-p`, `codex exec`), rate-limited. Desktop apps and editor panels cannot be woken; you are notified instead.
- The dashboard shows the same things live.

## 9. Concurrency

Every app starts its own server process, so several processes write to one database. SQLite runs in WAL mode (readers never block writers) with a 10-second busy timeout. Every check-then-write runs inside `BEGIN IMMEDIATE`, so two models claiming the same task at the same moment get exactly one winner (tested with four processes). IDs (T1, A2, ...) are allocated inside the same transactions. Proofs run in detached processes and write their result back, so they survive the chat that started them.

## 10. How failures are handled

The approach is the same everywhere: refuse early with the exact fix, never leave anything half-done, never touch your files or settings without a backup, and record what happened. These are the main groups; [edge-cases.md](edge-cases.md) lists them one by one.

| Kind of failure | Examples | How it is handled |
| --- | --- | --- |
| Two things at once | Two models claim one task; several write at the same time | Locked transactions: one winner, the other is told who has it; busy waits up to 10 s, then "try again" |
| Half-done work | Claim recorded but the git branch switch fails | Undone automatically |
| A model's chat dies | Crash, closed window, laptop sleeps | Leases expire after 30 minutes; the seat can be freed (`rt seat release`, or **Free the seat**); a new chat rejoins with the same history |
| A model breaks the rules | Edits files it doesn't lease; skips the hook with `--no-verify`; claims without reading updates; follows instructions found in another model's text | Commit refused; close refused; claim refused until it syncs; other models' text is marked as data and commands only come from the plan you locked |
| Tests misbehave | Hang, print megabytes, leave `__pycache__`, the runner is killed, output lost when killed | Time limit kills the process tree; last 40 lines kept; build leftovers ignored; dead runner detected and the task returned; Python output unbuffered so a stopped run still shows its output |
| Sandboxes | Codex cannot write `.git` | `commit=true`: Roundtable commits the leased files itself |
| Git trouble | Conflicts; your folder has changes or is on another branch; no commits; no identity; existing hooks; a working copy deleted by hand | Merge aborted cleanly and the owner alerted; merges wait and retry without touching your files; clear refusals with the exact command; hooks chained, never replaced; `rt doctor` finds it and `rt seat worktree` repairs it |
| App settings | Existing config files, unparseable files, Python moved, a project that tracks `.mcp.json` | Merged with a timestamped backup; unparseable files left alone with an explanation; full Python path used and `rt doctor` flags stale entries; tracked files left alone with manual steps |
| Opening apps | No terminal program, a terminal that rejects its arguments, no `code` command | The dashboard says so and shows the command to paste; failures are detected, not silent |
| Versions | Old database, newer database, new MCP protocol, official SDK changes | Automatic migration with a backup; "upgrade Roundtable" for newer databases; fallback handshake; tested against official MCP clients 1.x and 2.x |
| Your mistakes | Typo in a setting; `rt init` in the wrong folder; project in Dropbox | Refused with the right setting suggested; pointed to the right folder; `rt doctor` warns about syncing |
| Platform differences | Windows paths and consoles, Python 3.13's change to absolute paths on Windows, slow name lookup on some Macs | Handled in code; CI runs every test on Linux, macOS and Windows with Python 3.10 to 3.14 |
| Background runs | The app is not signed in, not installed, or hangs; the old session is gone; the dashboard is closed; two runners for one seat | The app's own error is shown and the run backs off (1 to 30 minutes); not installed is refused with the install command; runs stop at the time limit; a missing session falls back to a fresh one; runners are their own processes and keep going; a second runner is refused |
| Bugs in Roundtable | Anything unexpected | Logged with a traceback to `errors.log`; the model gets a clear message and keeps working; the dashboard shows the error instead of crashing |

### What is not covered

Being honest about the limits:

- **One computer.** All models must run on the machine that holds the project. There is no sync across computers yet.
- **Background runs only for Claude Code and Codex.** Other apps act only while you talk to them. A background runner does not restart itself after your computer restarts; start it again from the dashboard.
- **Models can still do harm with their own shell.** The rules stop mix-ups between cooperating models; they are not a security wall. A model with shell access can do anything you can, and the test commands you lock run with your permissions.
- **Some apps are verified only against their documentation.** Claude Code and Codex were tested for real; Gemini CLI, Qwen Code, opencode, Copilot CLI, Cursor and the VS Code panels follow their documented settings formats but have not been run with a real sign-in.
- **Tests decide "done".** If a task's test command is weak, a weak change can pass. That is why you read the commands before locking, and why review depth exists.

## 11. How it is tested

104 automated tests, run by GitHub Actions on Linux, macOS and Windows with Python 3.10 to 3.14 on every push. They cover whole projects from goal to merge, four processes claiming one task at once, timeouts and killed runners, merge conflicts, the commit guard and chained hooks, setting files for every app, migration of an old database, the dashboard's API and its security checks, the terminal and editor openers, and the MCP protocol with the official client libraries, and a whole project driven end to end by background runs of stand-in Claude Code and Codex programs that speak the real protocol (planning, building, tests, review, merge, quick mode, failures, starting and stopping), plus the benchmark harness and its hidden tests checked against a reference solution. The first real run, with Claude Code (Claude Opus 5.5) and Codex (GPT-6.1 Sol), went through blind drafts, critique, merge and approval as designed.
