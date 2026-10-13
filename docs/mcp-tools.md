# MCP tools reference

Roundtable gives every seat these 8 tools. Every tool also accepts `key` (the seat key from joining; not needed when the session is bound to a seat) and `format` (`text` or `json`). Each reply starts with the seat's inbox line, e.g. `[rt: 2 new · 1 review for you]`.

This page is generated from the code by `scripts/gen_docs.py`.

## rt_sync

Start here every session: what changed since you last looked and what needs you. First call in a chat: join="<your seat name>".

First call in a new chat: `rt_sync join="<seat>"` returns your key and the rules.

| Action | Parameters | What it does |
| --- | --- | --- |
| `seats` | none | List seats |
| `sync` | `full` (optional) true/false | What changed since you last looked, and what needs you |

## rt_plan

Plan together: blind drafts, critique, propose, approve or object, amendments to the locked plan.

| Action | Parameters | What it does |
| --- | --- | --- |
| `draft` | `text` text<br>`tasks` list of objects | Submit your blind plan draft (others cannot see it until all are in) |
| `view` | `draft` (optional) text | See the plan as far as you are allowed right now |
| `critique` | `draft` text<br>`points` list of objects<br>`reason` (optional) text | Critique a draft assigned to you |
| `propose` | `text` text<br>`tasks` list of objects | Chair: propose the merged plan |
| `approve` | `reason` (optional) text | Approve the proposed plan |
| `object` | `reason` text | Object to the proposed plan, with a reason |
| `amend` | `kind` text: edit_task / add_task / change_files / change_owner / cancel_task / change_proof / remove_dep<br>`task` (optional) text<br>`change` object<br>`reason` text | Propose a change to the locked plan |
| `amend_vote` | `id` text<br>`decision` text: approve / reject<br>`reason` (optional) text | Approve or reject an amendment that needs you |

## rt_task

Your work: ready tasks, claim (leases its files), checkpoint, close (Roundtable runs the proof), show, now.

| Action | Parameters | What it does |
| --- | --- | --- |
| `ready` | none | Tasks you can claim, and your current ones |
| `claim` | `task` text | Claim a ready task (leases its files) or resume your own |
| `checkpoint` | `task` text<br>`summary` text<br>`line` (optional) text | Save progress with a short summary |
| `close` | `task` text<br>`summary` text | Finish: Roundtable runs the task's proof, then review |
| `show` | `task` text<br>`zoom` (optional) text: L0 / L1 / L2 | Read a task at zoom L0, L1 or L2 |
| `now` | `text` text | Set your one-line 'now doing' (others see it) |

## rt_lease

Lease more files for your task, or give them back.

| Action | Parameters | What it does |
| --- | --- | --- |
| `extend` | `task` text<br>`files` list of text<br>`reason` (optional) text | Lease more files for your task |
| `release` | `task` (optional) text<br>`files` (optional) list of text | Give files back early |

## rt_review

Review others' tasks at the depth the human set; answer review comments on yours.

| Action | Parameters | What it does |
| --- | --- | --- |
| `queue` | none | Reviews assigned to you |
| `get` | `task` text | What you may read for a review, at the chosen depth |
| `submit` | `task` text<br>`verdict` text: approve / changes<br>`points` (optional) list of text<br>`comments` (optional) list of objects | Approve or request changes |
| `reply` | `id` text<br>`text` text<br>`resolve` (optional) true/false | Owner: answer a line comment (resolves it) |
| `ask_level` | `task` text<br>`level` text: mid / high<br>`reason` text | Ask the human for a deeper review of one task |

## rt_suggest

Advise the owner of a task or file instead of editing it; answer suggestions sent to you.

| Action | Parameters | What it does |
| --- | --- | --- |
| `send` | `text` text<br>`task` (optional) text<br>`file` (optional) text<br>`to` (optional) text<br>`patch` (optional) text | Advise the owner of a task or file (instead of editing it) |
| `reply` | `id` text<br>`status` text: accepted / rejected / later<br>`reason` text | Answer a suggestion sent to you |
| `list` | `all` (optional) true/false | Suggestions to you (open) and your sent ones |

## rt_alert

Problems, level 1-5 (4 and 5 need evidence): raise, ack, resolve, show, list.

| Action | Parameters | What it does |
| --- | --- | --- |
| `raise` | `level` number<br>`title` text<br>`description` (optional) text<br>`evidence` (optional) text<br>`files` (optional) list of text<br>`tasks` (optional) list of text | Raise a problem, level 1-5 |
| `ack` | `id` text<br>`note` (optional) text | Acknowledge an alert you have read |
| `resolve` | `id` text<br>`resolution` text | Close an alert with what fixed it |
| `propose_level` | `id` text<br>`level` number<br>`reason` text | Suggest a different level; the human decides |
| `show` | `id` text | Read one alert |
| `list` | `all` (optional) true/false | Open alerts (all=true includes resolved) |

## rt_vote

Settle stuck decisions by vote; every ballot needs a reason.

| Action | Parameters | What it does |
| --- | --- | --- |
| `open` | `topic` text<br>`options` list of text<br>`voters` (optional) list of text | Put a stuck decision to all seats |
| `cast` | `id` text<br>`choice` text<br>`reason` text | Vote, with your reason (your argument) |
| `show` | `id` (optional) text | Read a vote and the arguments |

