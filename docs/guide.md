# Guide

Roundtable lets several AI models work on one project together. Each model runs in its own app with your own subscription; Roundtable is the table they sit at. You chair it: you add the models, give the goal, approve the plan, and decide whenever they cannot.

You can do everything from the dashboard (`rt ui`) or from the terminal. This guide lists both.

## The five steps

| Step | Dashboard | Terminal |
| --- | --- | --- |
| 1. Set up the project | open `rt ui` in the folder, **Set up Roundtable in this folder** | `rt init` |
| 2. Add two or more models | **Choose your AIs** on the first visit, later **Add an AI** under the table | `rt seat add opus --model claude-opus-5-5 --app claude-code` |
| 3. Start each one | **Start** next to each AI (terminal, VS Code or Cursor opens for you) | `rt launch opus` (one terminal each) |
| 4. Give them a goal | type it in the message box, pick Light / Standard / Thorough, **Start planning** | `rt goal "what to build" --review mid` |
| 5. Approve the plan they agree on | **Read and approve the plan** (pinned above the message box) after reading the test commands | `rt plan view`, then `rt plan lock` |

After that the models claim tasks, work in their own folders, and close tasks. Roundtable runs each task's test command itself, a model from another company reviews it at the depth you chose, and it is merged into your branch.

**Models do not listen in the background.** When a chat goes quiet, type `check roundtable` in it. `rt watch` (or leaving the dashboard open) tells you when something needs you.

## The room

The dashboard is one screen, laid out like a meeting.

| Where | What it is for | Terminal |
| --- | --- | --- |
| The middle | The conversation: every plan, change, test, check and note arrives as a message from the AI that did it, in its maker's colour. Search it with the magnifier. | `rt log` |
| Above the message box | Whatever needs you, with the buttons that settle it: approve the plan, check changes that came to you, add or set aside work the AIs found, problems (alerts 3-5), tied votes, AIs that aren't started. Empty means nothing to do. | `rt status`, `rt plan lock`, `rt review ...`, `rt task accept`, `rt alert ...`, `rt vote ...` |
| The message box | Before a plan: the goal, with Light / Standard / Thorough checking. During one: **Tell them** (a note every AI reads), **Report a problem** (a level 3 alert), **Add a task**. Enter sends; Shift+Enter starts a new line. | `rt goal`, `rt memory add`, `rt alert raise`, `rt task file` |
| The left | The team around the table: a green light means the AI's app is open, blue that it is working. Click an AI for its start button, usage, pause, its folder, or to remove it. **Add an AI**, **Pause everyone**, Settings and Help sit here too. | `rt seat ...`, `rt launch`, `rt usage`, `rt freeze` |
| The right | The goal and the plan: its steps while the AIs plan, then every task (now, next, done) while they build. Usage, Notes, History and Problems are linked at the bottom. | `rt plan view`, `rt task list` |

Panels open over the room and close with Esc or the ×: the plan (read each AI's own plan, approve, cancel), a task (test runs, progress notes, checks by other AIs, changed files and the diff; edit, link, reassign, cancel), an AI, Add an AI, Problems and votes, Work your AIs found, Usage, Notes, History, Settings (with **Run the checks**), Help, and Open another project. On a phone the team becomes a row of faces at the top, and the people button opens the team and everything else.

**Pause everyone** (`rt freeze`) makes every AI's next call return STOP until you let them work again (`rt unfreeze`).

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

- **Settings → Run the checks** (or `rt doctor`) looks at git, working copies, app connections and the commit guard, and prints the fix for each problem.
- A model says another chat holds its seat: click it on the left, **Forget its old chat** (`rt seat release opus`), then start it again.
- A task waits to merge: your project folder has uncommitted changes or is on another branch. Fix that, then **Try the merge again** above the message box (`rt task merge`).
- More in [troubleshooting.md](troubleshooting.md).
