# Guide

Roundtable lets several AI models work on one project together. Each model runs in its own app with your own subscription; Roundtable is the table they sit at. You chair it: you add the models, give the goal, approve the plan, and decide whenever they cannot.

You can do everything from the app or from the terminal. This guide lists both. Open the app from your app menu ("Roundtable"), or with `rt app` in a terminal; `rt app --install` adds it to the menu if the installer didn't.

## The five steps

| Step | App | Terminal |
| --- | --- | --- |
| 1. Set up the project | open the app, **Browse…** to your folder, **Set up Roundtable in this folder** | `rt init` |
| 2. Add two or more models | **Choose your AIs** on the first visit, later **Add an AI** under the table | `rt seat add opus --model claude-opus-5-5 --app claude-code` |
| 3. Start each one | **Run in the background** (Claude Code, Codex, opencode), or **Open a terminal**; VS Code and Cursor open for you | `rt run opus --detach`, or `rt launch opus` (one terminal each) |
| 4. Give them a goal | type it in the message box; **Plan together** or **Just do it**; Light / Standard / Thorough; optionally **Start without asking me** | `rt goal "what to build" --review mid` (`--quick`, `--auto`) |
| 5. Approve the plan they agree on | **Read and approve the plan** (pinned above the message box) after reading the test commands | `rt plan view`, then `rt plan lock` |

After that the models claim tasks, work in their own folders, and close tasks. Roundtable runs each task's test command itself, a model from another company reviews it at the depth you chose, and it is merged into your branch.

**Models only act while something starts them.** An AI that runs in the background is started by Roundtable whenever it has work: a plan to write, a plan to comment on or agree to, a task to build or fix, a change to check, a problem to acknowledge, or a message from you. An AI you opened yourself acts only while you talk to it: when its chat goes quiet, type `check roundtable` in it. If the plan is waiting for an AI that isn't running, the room says so with a button to fix it.

## Running in the background

- **Start / stop:** in the AI's panel (click it on the left), or `rt run opus --detach` and `rt run opus --stop`. `rt run opus` keeps it in the current terminal instead.
- **What it may do:** by default edit files in its own working copy, use the Roundtable tools and git, and run the project's own test commands; other commands are refused. Settings → Background runs → "Any command" lifts that (`runner.permissions = "all"`).
- **What you see:** its thinking, the commands it runs and the files it edits, live at the bottom of the conversation and in full in its panel.
- **When it fails:** a run that changes nothing is not repeated at once; the wait doubles from 1 to 30 minutes and the room shows it as stuck, with the app's own error (for example "not signed in"). **Try again now** retries at once. A run is stopped after 45 minutes (`runner.max_minutes`).
- **Sessions:** each run continues the same conversation, so the AI remembers earlier runs; if that conversation is gone, it starts a fresh one by itself.
- **Model and thinking:** in the AI's panel, pick the model and how hard it thinks (Claude Code: low to max; Codex: minimal to extra high). Background runs use it from their next start (`rt seat set opus --effort high`).

## Ask the table

Choose **Ask the table** in the message box (or `rt ask "your question"`) to ask anything: about your code, a design choice, why a bug happens.

1. Every AI you ticked under "Who answers" answers on its own. They can read your project and its git history, but can't change anything.
2. Each one then reads all the answers as Answer A, B, C, in random order and without names, says what is right and wrong in each, and ranks them, its own included.
3. The AI whose answer the others ranked best writes the final answer from all the answers and reviews.

The question appears in the conversation with each AI's progress, then the final answer and where each AI's answer was ranked. **See every answer** opens every answer, every review and the ranking table. **Ask a follow-up** keeps the context; **Build this** puts the answer in the message box so you can turn it into a goal. Only AIs Roundtable can run by itself (Claude Code, Codex, opencode) can answer. `rt ask --list` and `rt ask --show Q2` show earlier questions.

**Second opinions** happen by themselves: when a task fails its tests twice in a row, an AI from another company reads the failure in the builder's copy of the project and sends the builder a diagnosis, which it must answer. Settings → Asking the table turns this off.

## Choosing a model

The model box in **Add an AI** and in each AI's panel lists the app's own models: Claude Code's, Codex's own list (with the thinking levels each model has), and every opencode model, with the free ones marked and a **Free only** filter. Type any other name the app accepts. opencode's free models need no account, so a third AI at the table can cost nothing.

## Plan together, or just do it

- **Plan together** (default): up to three AIs each write a plan without seeing the others', comment on each other's without knowing who wrote which, one combines them and the others agree. Best for bigger changes.
- **Just do it** (`rt goal "..." --quick`): one AI splits your message into tasks at once, giving named parts to the AIs you named ("sol: ... opus: ..."). Tests and checks still run.
- **Start without asking me** (`--auto`): the plan starts as soon as it is ready. Its test commands then run on your computer without you reading them first.

## The room

The app is one calm screen: a conversation, with everything else one click away.

| Where | What it is for | Terminal |
| --- | --- | --- |
| The middle | The conversation: every plan, change, test, check, question and note arrives as a message from the AI that did it, in its maker's colour, with long messages folded behind **Read more**. At the bottom, a quiet line for each AI that is working right now (thinking, running a command, editing a file). | `rt log` |
| Above the message box | Whatever needs you, with the buttons that settle it: approve the plan, check changes that came to you, add or set aside work the AIs found, problems (alerts 3-5), tied votes, AIs that aren't started or are out of usage. Empty means nothing to do. | `rt status`, `rt plan lock`, `rt review ...`, `rt task accept`, `rt alert ...`, `rt vote ...` |
| The message box | Before a plan: **Plan together**, **Just do it** or **Ask the table**; the small options link sets how carefully they check (Light / Standard / Thorough) and whether they start without asking you. During a plan: **Tell them** (a note every AI reads), **Ask the table**, **Report a problem** (a level 3 alert), **Add a task**. Enter sends; Shift+Enter starts a new line. | `rt goal`, `rt ask`, `rt memory add`, `rt alert raise`, `rt task file` |
| The bar on top | The project (click to switch), what is happening now, and your AIs as faces: a green dot means its app is open, blue that it is working, amber that it needs you. Click a face for its start button, model, usage and everything it did. **Plan**, search and the menu sit on the right. | `rt seat ...`, `rt launch`, `rt usage` |
| The menu | The team, the plan and its tasks, questions to the table, problems, work your AIs found, usage, notes, history, settings, help, another project, **Pause everyone**. | `rt plan view`, `rt task list`, `rt ask --list`, `rt freeze` |

Sheets open over the conversation and close with Esc or the ×: the plan (read each AI's own plan, approve, cancel), a task (test runs, progress notes, checks by other AIs, changed files and the diff; edit, link, reassign, cancel), an AI, a question to the table, Add an AI, Problems and votes, Work your AIs found, Usage, Notes, History, Settings (with **Run the checks**), Help, and Open another project. It works the same on a phone.

**Pause everyone** (`rt freeze`) makes every AI's next call return STOP until you let them work again (`rt unfreeze`).

The app uses plain words; the terminal and the AIs' own messages use the older names. Approve the plan = lock. Tests = proof. Light / Standard / Thorough checking = review depth low / mid / high. Work your AIs found = backlog. An AI on the team = a seat.

## Words you will see

- **Model, or seat.** One model in one app, with a short name like `opus`. Commands call it a seat.
- **Working copy.** A separate folder per coding model, next to your project (`yourproject.opus`), on its own git branch. Your own folder is never edited by the models.
- **Lease.** Claiming a task leases its files to that model. Others can read them and send suggestions, not edit or commit them.
- **Test command (proof).** The command that shows a task works. Roundtable runs it; a model saying "done" is not enough.
- **Review depth.** Low: no code review between models, tests are the gate. Mid: a model from another company reads a map of each change, and the full code of 1 task in 5 and of risky tasks. High: two models read every line and leave comments that must be answered. This is separate from how hard each model thinks.
- **Backlog.** Work a model found while doing something else. It waits for your yes.
- **Epic.** A group of tasks; done when they are.
- **Memory.** Short notes that outlive chats.
- **Alert levels.** 1 note, 2 heads-up, 3 the affected models must acknowledge, 4 holds the files, 5 freezes them and stops everyone.

## When something looks wrong

- **Settings → Run the checks** (or `rt doctor`) looks at git, working copies, app connections and the commit guard, and prints the fix for each problem.
- A model says another chat holds its seat: click it on the left, **Forget its old chat** (`rt seat release opus`), then start it again.
- A task waits to merge: your project folder has uncommitted changes or is on another branch. Fix that, then **Try the merge again** above the message box (`rt task merge`).
- More in [troubleshooting.md](troubleshooting.md).
