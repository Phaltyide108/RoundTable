# Changelog

## 0.4.0 (2026-10-14)

- **Ask the table.** Choose "Ask the table" in the message box (or `rt ask "..."`): every AI answers on its own, they rank each other's answers without names (Answer A, B, C), and the one whose answer the others ranked best writes the final answer, fixing what the reviews found wrong. They can read your project but change nothing. The conversation shows it live; a panel shows every answer, every review and how they ranked each other; "Build this" turns the answer into a goal, "Ask a follow-up" keeps the context. This is Andrej Karpathy's LLM Council, run with your own subscriptions and with your code open to it.
- **Second opinions.** When a task fails its tests twice in a row, an AI from another company reads the failure in the builder's copy of the project and sends the builder a diagnosis it must answer (`council.rescue`, on by default).
- **opencode runs in the background too**, like Claude Code and Codex, with any of its models, including the free ones. Its permissions and its connection to Roundtable are passed in for each run, so no file changes.
- **Every model, not a short list.** The model picker shows each app's own list: Claude Code's models, Codex's own list (with the thinking levels each model has, up to max and ultra), and all of opencode's models with the free ones marked and a "Free only" filter. Roundtable now knows the makers behind opencode's models (GLM, Kimi, DeepSeek, Qwen, MiniMax, ...) so reviews still go to another company.
- **When an AI runs out of usage, the others carry on.** Found in a real benchmark run, when Claude's 5-hour limit ran out halfway through a team's work: Roundtable now recognises the apps' "you've hit your limit · resets 9:20pm" messages, shows "out of usage until 21:20" instead of "stuck", stops retrying until then, and hands that AI's unfinished tasks and open reviews to the others. The next builder's branch starts from the previous one's work, so nothing done is lost. Questions to the table skip it until it is back.
- **A harder benchmark.** `rt bench run --task sql`: a SQL engine that must answer exactly like SQLite (NULL logic, integer division, type affinity, ordering, GROUP BY, joins), scored with 111 hidden tests that compare against real SQLite. The spreadsheet task turned out too easy: Claude Opus 5.5 and GPT-6.1 Sol each passed all 52 of its hidden tests alone. Reports now say when a contender ran out of usage, and score a stopped team's unmerged work too.
- **A smarter council.** When the AIs' answers are numbered items, Roundtable lists the items where they disagree and has the reviewers and the final writer work each of those out again, on the merits; council members may check facts and numbers with `python -c` (Codex stays in its read-only sandbox). On a hard 30-question quiz at low thinking, Claude Haiku and GPT-6 Luna together then scored 30/30 three times, against 28-29 for Haiku alone and 17-18 for Luna alone.
- **A new layout, like the chat apps you know.** A sidebar with your project, "New goal" and "Ask the table", your questions as a history list and your team with what each one is doing; on wide windows a right-hand panel shows each AI's latest step live, the plan's progress and its tasks. Larger type (Geist), three themes (Snow, Midnight, Paper). Ctrl+K searches, Ctrl+B hides the sidebar.
- **Each question to the table gets its own page**, like LLM Council: the stages as they happen, the final answer first (with Copy), then each AI's own answer in tabs or side by side, and a table of who ranked whom. Follow-ups are asked from the same page.
- **Selecting text works.** Automatic updates used to redraw the page every few seconds and wipe what you were selecting; they now wait while you select. Ctrl+A selects the conversation (or the open panel), not the buttons around it. Selected text is now shown in a clear blue (the pale green was invisible on white).
- **A benchmark nobody can have memorised.** `rt bench run --task fresh`: 20 competition-style problems (number theory, counting, recurrences, lattice geometry, digits) made up from a seed for each run, every answer computed by a program, tools off for everyone; `--seed N` repeats a run. AIME 2025 turned out to be in the models' training data: Claude Haiku at low thinking scored 30/30 and said it recalled some answers. Questions to the table can now be up to 16,000 characters (the AIME set did not fit in 6,000).
- **Benchmarks show whether combining helped, question by question.** For a team, each member's own answer (written before it saw the others') is scored too, and the report has a table of every question: the right answer, each member's, the team's. Quiz prompts now require an answer for every problem (GPT-6 Luna declined to answer at all with tools off). The fresh problems are harder: towers of powers, necklaces up to rotation, 12-person seatings with five forbidden pairs, order-3 recurrences out to 10^15, digit sums with divisibility.
- **More benchmarks.** `pond` and `pondpro` (a three.js koi pond, scored in headless Chrome with a screenshot for you to judge; pondpro measures the physics against exact numbers), `quiz` and `quizhard` (questions with exact answers; a team answers by asking the table).
- **Fewer tokens for a team.** Measured in a benchmark: one small model used 666k tokens over 7 background runs, mostly re-reading its whole earlier conversation on every wake-up. A background run now continues the previous conversation only while the app's prompt cache is still warm (`runner.resume_minutes`, 5); otherwise it starts fresh, and Roundtable's digest tells it what happened. Planners are told to keep tasks few (about one per builder), since every task costs a run and a review.
- Answers and diagnoses from the AIs are shown as formatted text (headings, lists, code, tables).
- "Browse…" opens your computer's own folder chooser when you open or set up a project; recent projects are one click away.
- **Roundtable is an app now.** `rt app` (and `rt ui`) opens it in its own window instead of a browser tab: a native GTK/WebKit window on Linux, otherwise Chrome, Edge or Brave in app mode (no tabs, no address bar), with your default browser only as a last resort. `rt app --install` adds it to your app menu (Linux), Launchpad (macOS) or the Start menu (Windows), with its own icon. Started from the menu, it finds `claude` and `codex` on your terminal's PATH and opens your most recent project. `rt ui --browser` keeps the old way.
- Tested for real with Claude Code 2.1.299 and Codex 0.159 running in the background, which found and fixed:
  - Codex refused every Roundtable tool in background runs ("approval policy is never"). Roundtable's tools are now pre-approved for Codex (`default_tools_approval_mode`), also in `rt setup codex`.
  - In quick mode the planning AI saw the goal cut at 80 characters and dropped the parts meant for other AIs. It now gets the whole goal and is told to keep every named part with its AI.
  - Test commands that cannot run on this computer (`python` when only `python3` exists, pytest not installed) are refused when the plan is written, with the fix, instead of failing after the work is done.
  - An AI waiting for a change it asked for (or a problem it raised) was woken again and again; it now waits until that is settled. The same work is resumed at most 3 times in a row before it counts as stuck, and "stuck" shows the AI's own last words.
  - Token counts no longer count cached context again on every step.
  - Activity shows the real error instead of Roundtable's inbox line, Codex tool errors, and Codex commands without their `bash -lc` wrapper.

## 0.3.0 (2026-10-14)

- **Background runs.** Roundtable now starts Claude Code and Codex by itself, with your own logins, whenever an AI has work, and lets it sleep when it is done (`rt run <seat>`, or **Run in the background** in the dashboard). Nothing waits any more for someone to type "check roundtable". Runs continue the same session, back off when stuck and say why, stop at a time limit, and only edit their own working copy, use git and run the project's tests unless you allow more (`runner.permissions`).
- **See what they are doing.** Thinking, commands, edits and errors appear live at the bottom of the conversation and in full in each AI's panel, from background runs and from Claude Code and Codex chats you opened yourself.
- **Model and thinking per AI.** Change an AI's model and how hard it thinks from its panel or with `rt seat set opus --effort high` (Claude Code `--effort`, Codex `model_reasoning_effort`).
- **Just do it.** `rt goal "..." --quick` (or **Just do it** in the message box) skips the planning rounds: one AI splits your message into tasks, giving named parts to the AIs you named. **Start without asking me** (`--auto`) starts the work without your approval.
- **`rt bench`**: the same task for each AI alone and for the team, scored with 52 hidden tests (a spreadsheet engine specification), with minutes and tokens.
- The room says when nothing is happening because the AIs it waits on aren't running, with a button to start them.
- Usage: a 5-hour or weekly window that has reset is shown as reset, not as its old percentage; numbers show how old they are.
- Long messages fold behind **Read more**; the goal is shown in full.
- Fixed: the plan's chair was told to approve its own plan; seats started with `rt launch` never showed as active; environment variables of a Claude Code session leaked into apps started from `rt ui`.
- Database schema 3 (seat effort, plan mode), migrated automatically with a backup.

## Earlier in 0.3

- **The dashboard is now a room.** One screen instead of sections:
  - The middle is a conversation. Everything the AIs do arrives as a message from the AI that did it, in its maker's colour, in plain words ("Started T2", "T2 passed its tests", "Asked for changes in T3").
  - Whatever needs you is pinned above the message box with the buttons that settle it: approve the plan, check changes, add or set aside work the AIs found, problems, tied votes, and a Start button for each AI that isn't running yet.
  - The message box gives the goal (with Light / Standard / Thorough checking) and, once there is a plan, sends notes, problems and tasks. Enter sends.
  - The team sits around a drawn table on the left, lit while each app is open; the plan's steps, then every task, are on the right.
  - Everything else (a task with its tests and diff, an AI with its usage, settings, help) opens as a panel over the room and closes with Esc.
  - First visit is three steps: choose your AIs (tick several apps at once; names and models filled in), start them, give them a goal.
  - Bundled Atkinson Hyperlegible Next for legibility; light and dark; works on phones. Old dashboard links still work.

## 0.2.0 (2026-10-13)

- **Dashboard first.** `rt ui` now covers every human action: set up a folder, add and start models (opens a terminal window, VS Code or Cursor), connect apps, start and lock plans after reading the test commands, file and accept tasks, review with diffs, alerts and votes, usage, memory, history search, settings with setup checks, and a built-in guide. Works outside a project, remembers recent projects, light and dark, phones.
- **Tracking like Beads:** task kinds, priorities P0-P4 and labels; epics; waits_for / related / discovered_from / parent links; models file discovered work into a backlog you accept; project memory shown to every model when it joins; `rt compact`.
- **More apps:** Claude Code and Codex in VS Code, Gemini CLI, Qwen Code, opencode, GitHub Copilot CLI (`rt setup copilot`) and Cursor. Per-seat settings files bind each app to its model and stay out of git.
- `commit=true` on checkpoint/close lets Roundtable commit for apps whose sandbox keeps `.git` read-only (Codex).
- Plain `rt` tells you the next step; `rt --help` groups commands by purpose. New docs/guide.md.
- Database schema 2, migrated automatically with a backup.
- Fixes found by CI: lost output of hung test runs, slow dashboard start on some Macs, rooted paths on Windows with Python 3.13.


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
