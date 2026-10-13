# Guide

Roundtable lets several AI models work on one project together. Each model runs in its own app with your own subscription; Roundtable is the table they sit at. You chair it: you add the models, give the goal, approve the plan, and decide whenever they cannot.

You can do everything from the dashboard (`rt ui`) or from the terminal. This guide lists both.

## The five steps

| Step | Dashboard | Terminal |
| --- | --- | --- |
| 1. Set up the project | open `rt ui` in the folder, **Set up Roundtable in this folder** | `rt init` |
| 2. Add two or more models | **Models → Add a model** | `rt seat add opus --model claude-opus-5-5 --app claude-code` |
| 3. Start each one | **Models → Start** (terminal, VS Code or Cursor opens for you) | `rt launch opus` (one terminal each) |
| 4. Give them a goal | **Plan → Start a plan** | `rt goal "what to build" --review mid` |
| 5. Lock the plan they agree on | **Plan → Lock the plan** after reading the test commands | `rt plan view`, then `rt plan lock` |

After that the models claim tasks, work in their own folders, and close tasks. Roundtable runs each task's test command itself, a model from another company reviews it at the depth you chose, and it is merged into your branch.

**Models do not listen in the background.** When a chat goes quiet, type `check roundtable` in it. `rt watch` (or leaving the dashboard open) tells you when something needs you.

## Dashboard pages

| Page | What it is for | Terminal |
| --- | --- | --- |
| Overview | What needs you right now, with the button that settles it; the table (who is doing what); work in progress; latest activity | `rt status` |
| Plan | Start a plan; follow drafts, critiques and approvals; read each model's own plan; lock; approve changes to a locked plan | `rt goal`, `rt plan view/lock/continue/cancel/amend-decide` |
| Tasks | Every task by priority; filter by status, kind and text; file new work; accept backlog items; edit, link, reassign, cancel; test runs, reviews and history per task | `rt task list/show/file/accept/edit/link/reassign/cancel/merge` |
| Reviews | Reviews that came to you (with the diff), requests for deeper reviews, what models are reviewing now | `rt review queue/get/submit/level-decide` |
| Alerts and votes | Problems raised at levels 1-5; resolve or change their level; raise your own; decide votes | `rt alert ...`, `rt vote ...` |
| Models | Add, start, pause, free, remove models; connect apps you open yourself | `rt seat ...`, `rt launch`, `rt setup` |
| Usage | Each model's context, 5-hour and 7-day limits, and what coordinating cost | `rt usage` |
| Memory | Notes every model sees when it joins | `rt memory add/list/pin/forget` |
| Activity | Full history with search | `rt log` |
| Settings | Every setting with an explanation; setup checks; compaction and export | `rt config`, `rt doctor`, `rt compact`, `rt export` |
| Guide | This page, inside the dashboard | |

The red **Stop all models** button (`rt freeze`) makes every model's next call return STOP until you let them work again (`rt unfreeze`).

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
- A model says another chat holds its seat: **Models → Free the seat** (`rt seat release opus`), then start it again.
- A task waits to merge: your project folder has uncommitted changes or is on another branch. Fix that, then **Try the merge again** (`rt task merge`).
- More in [troubleshooting.md](troubleshooting.md).
