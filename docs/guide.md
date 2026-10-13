# Guide

Roundtable lets several AI models work on one project together. Each model runs in its own app with your own subscription; Roundtable is the table they sit at. You chair it: you add the models, give the goal, approve the plan, and decide whenever they cannot.

You can do everything from the dashboard (`rt ui`) or from the terminal. This guide lists both.

## The five steps

| Step | Dashboard | Terminal |
| --- | --- | --- |
| 1. Set up the project | open `rt ui` in the folder, **Set up Roundtable in this folder** | `rt init` |
| 2. Add two or more models | **Team → Add an AI model** | `rt seat add opus --model claude-opus-5-5 --app claude-code` |
| 3. Start each one | **Team → Start** (terminal, VS Code or Cursor opens for you) | `rt launch opus` (one terminal each) |
| 4. Give them a goal | **Plan → Start planning** | `rt goal "what to build" --review mid` |
| 5. Approve the plan they agree on | **Inbox / Plan → Approve the plan** after reading the test commands | `rt plan view`, then `rt plan lock` |

After that the models claim tasks, work in their own folders, and close tasks. Roundtable runs each task's test command itself, a model from another company reviews it at the depth you chose, and it is merged into your branch.

**Models do not listen in the background.** When a chat goes quiet, type `check roundtable` in it. `rt watch` (or leaving the dashboard open) tells you when something needs you.

## Dashboard pages

Five sections, plus **More** for the pages you need less often. On a phone they sit in a tab bar at the bottom. Every page has a **?** button that explains it in two or three sentences.

| Page | What it is for | Terminal |
| --- | --- | --- |
| Home | What is happening, the one thing to do next (one big button), the steps from adding AIs to finished work, who is doing what at the table, latest activity | `rt status` |
| Inbox | Every decision in one place: approve the plan, check changes that came to you, accept or turn down work the AIs found, problems (alerts 1-5) and votes; tell the AIs about a problem yourself | `rt plan lock`, `rt review ...`, `rt task accept`, `rt alert ...`, `rt vote ...` |
| Team | Add an AI (pick the app, then name and model, filled in for you); start, pause, disconnect an old chat, remove; connect apps you open yourself | `rt seat ...`, `rt launch`, `rt setup` |
| Plan | Write the goal and choose Light / Standard / Thorough checking; follow the drafts, comments and agreement; read each AI's own plan; approve; cancel | `rt goal`, `rt plan view/lock/continue/cancel` |
| Work | A board: To do, In progress, Checking (tests and review), Done. Each task's page has its test runs, progress notes, checks by other AIs, changed files and history; add, edit, link, reassign, cancel | `rt task list/show/file/edit/link/reassign/cancel/merge` |
| More → Usage | Each AI's chat size, 5-hour and weekly limits, and what coordinating cost | `rt usage` |
| More → Notes | Notes every AI reads when it joins | `rt memory add/list/pin/forget` |
| More → History | Everything that happened, with search | `rt log` |
| More → Settings | Every setting in plain words; setup checks; tidy history; export | `rt config`, `rt doctor`, `rt compact`, `rt export` |
| More → Help | How it works, the words the AIs use, and the terminal command for every button | |

The **Stop all AIs** button at the top (`rt freeze`) makes every AI's next call return STOP until you let them work again (`rt unfreeze`).

The dashboard uses plain words; the terminal and the AIs' own messages use the older names. Approve the plan = lock. Tests = proof. Light / Standard / Thorough checking = review depth low / mid / high. Work your AIs found = backlog. An AI on the team = a seat.

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

- **More → Settings → Run the checks** (or `rt doctor`) looks at git, working copies, app connections and the commit guard, and prints the fix for each problem.
- A model says another chat holds its seat: **Team → ⋯ → Disconnect its old chat** (`rt seat release opus`), then start it again.
- A task waits to merge: your project folder has uncommitted changes or is on another branch. Fix that, then **Inbox → Try again** (`rt task merge`).
- More in [troubleshooting.md](troubleshooting.md).
