# Command reference

Generated from the code by `scripts/gen_docs.py`. Every command also accepts the global options below.

```text
usage: rt [-h] [--version] [--home HOME] [--seat AS_SEAT] [--key SEAT_KEY]
          [--json]
          command ...

Roundtable: AI models planning, building and reviewing one project together.

positional arguments:
  command
    init          set up Roundtable in this project
    status        overview: plan, seats, tasks, what waits on you
    log           history of events
    seat          manage seats (models)
    goal          start a plan
    plan          the plan
    task          tasks
    review        reviews assigned to you (the human)
    vote          votes
    alert         alerts
    freeze        stop all seats
    unfreeze      let seats work again
    config        settings
    export        write JSONL snapshots
    usage         context, tokens and 5h/7d limits per seat, plus Roundtable's
                  own token cost
    setup         connect an app to this project
    launch        start a seat's app
    doctor        check everything and suggest fixes
    watch         notify you and wake seats when needed
    ui            local dashboard in your browser
    mcp           run the MCP server (apps start this themselves)
    call          run any operation: rt call task.show task=T3
    version       print the version

options:
  -h, --help      show this help message and exit
  --version       show program's version number and exit
  --home HOME     project folder or its .roundtable folder (default: search
                  upward from here)
  --seat AS_SEAT  act as this seat (for apps without MCP)
  --key SEAT_KEY  act as the seat that joined with this key
  --json          print JSON
```

## rt init

```text
usage: rt init [-h] [--name NAME] [path]

positional arguments:
  path

options:
  -h, --help   show this help message and exit
  --name NAME
```

## rt status

```text
usage: rt status [-h]

options:
  -h, --help  show this help message and exit
```

## rt log

```text
usage: rt log [-h] [--since SINCE] [--limit LIMIT] [--task TASK]

options:
  -h, --help     show this help message and exit
  --since SINCE  event id or HH:MM
  --limit LIMIT
  --task TASK
```

## rt seat

```text
usage: rt seat [-h] action ...

positional arguments:
  action
    add       register a model as a seat
    list      list seats
    pause     pause a seat
    resume    resume a seat
    remove    remove a seat
    release   free a seat whose chat was closed
    worktree  create or repair its working copy

options:
  -h, --help  show this help message and exit
```

### rt seat add

```text
usage: rt seat add [-h] --model MODEL
                   --app {claude-code,claude-app,codex-cli,codex-app,other}
                   [--company COMPANY] [--roles ROLES] [--no-worktree]
                   handle

positional arguments:
  handle

options:
  -h, --help            show this help message and exit
  --model MODEL         model id the app understands, e.g. claude-opus-5-5
  --app {claude-code,claude-app,codex-cli,codex-app,other}
  --company COMPANY     anthropic, openai, google ... (guessed when omitted)
  --roles ROLES         comma list of plan,build,review (default all)
  --no-worktree         no separate working copy
```

### rt seat list

```text
usage: rt seat list [-h]

options:
  -h, --help  show this help message and exit
```

### rt seat pause

```text
usage: rt seat pause [-h] handle

positional arguments:
  handle

options:
  -h, --help  show this help message and exit
```

### rt seat resume

```text
usage: rt seat resume [-h] handle

positional arguments:
  handle

options:
  -h, --help  show this help message and exit
```

### rt seat remove

```text
usage: rt seat remove [-h] handle

positional arguments:
  handle

options:
  -h, --help  show this help message and exit
```

### rt seat release

```text
usage: rt seat release [-h] handle

positional arguments:
  handle

options:
  -h, --help  show this help message and exit
```

### rt seat worktree

```text
usage: rt seat worktree [-h] handle

positional arguments:
  handle

options:
  -h, --help  show this help message and exit
```

## rt goal

```text
usage: rt goal [-h] [--planners PLANNERS] [--review {low,mid,high}] goal

positional arguments:
  goal

options:
  -h, --help            show this help message and exit
  --planners PLANNERS   comma list of seats
  --review {low,mid,high}
```

## rt plan

```text
usage: rt plan [-h] action ...

positional arguments:
  action
    view          show the plan
    continue      move on without missing drafts/critiques
    lock          approve the plan; creates tasks
    cancel        cancel the active plan
    amend-decide  approve or reject an amendment

options:
  -h, --help      show this help message and exit
```

### rt plan view

```text
usage: rt plan view [-h] [--draft DRAFT]

options:
  -h, --help     show this help message and exit
  --draft DRAFT
```

### rt plan continue

```text
usage: rt plan continue [-h]

options:
  -h, --help  show this help message and exit
```

### rt plan lock

```text
usage: rt plan lock [-h] [--force] [--draft DRAFT]

options:
  -h, --help     show this help message and exit
  --force
  --draft DRAFT  lock a draft directly
```

### rt plan cancel

```text
usage: rt plan cancel [-h] reason

positional arguments:
  reason

options:
  -h, --help  show this help message and exit
```

### rt plan amend-decide

```text
usage: rt plan amend-decide [-h] id {approve,reject}

positional arguments:
  id
  {approve,reject}

options:
  -h, --help        show this help message and exit
```

## rt task

```text
usage: rt task [-h] action ...

positional arguments:
  action
    show          show a task
    cancel        cancel a task
    reassign      give a task to another seat
    merge         retry merges
    review-level  set one task's review depth

options:
  -h, --help      show this help message and exit
```

### rt task show

```text
usage: rt task show [-h] [--zoom {L0,L1,L2}] task

positional arguments:
  task

options:
  -h, --help         show this help message and exit
  --zoom {L0,L1,L2}
```

### rt task cancel

```text
usage: rt task cancel [-h] task reason

positional arguments:
  task
  reason

options:
  -h, --help  show this help message and exit
```

### rt task reassign

```text
usage: rt task reassign [-h] task [owner]

positional arguments:
  task
  owner

options:
  -h, --help  show this help message and exit
```

### rt task merge

```text
usage: rt task merge [-h] [task]

positional arguments:
  task

options:
  -h, --help  show this help message and exit
```

### rt task review-level

```text
usage: rt task review-level [-h] task {low,mid,high,default}

positional arguments:
  task
  {low,mid,high,default}

options:
  -h, --help            show this help message and exit
```

## rt review

```text
usage: rt review [-h] action ...

positional arguments:
  action
    queue         reviews waiting for you
    get           read a task for review
    submit        approve or request changes
    level-decide  approve/deny a deeper-review request

options:
  -h, --help      show this help message and exit
```

### rt review queue

```text
usage: rt review queue [-h]

options:
  -h, --help  show this help message and exit
```

### rt review get

```text
usage: rt review get [-h] task

positional arguments:
  task

options:
  -h, --help  show this help message and exit
```

### rt review submit

```text
usage: rt review submit [-h] [--point POINT] task {approve,changes}

positional arguments:
  task
  {approve,changes}

options:
  -h, --help         show this help message and exit
  --point POINT      repeatable
```

### rt review level-decide

```text
usage: rt review level-decide [-h] id {approve,deny}

positional arguments:
  id
  {approve,deny}

options:
  -h, --help      show this help message and exit
```

## rt vote

```text
usage: rt vote [-h] action ...

positional arguments:
  action
    show      open votes, or one
    decide    decide a vote

options:
  -h, --help  show this help message and exit
```

### rt vote show

```text
usage: rt vote show [-h] [id]

positional arguments:
  id

options:
  -h, --help  show this help message and exit
```

### rt vote decide

```text
usage: rt vote decide [-h] id choice

positional arguments:
  id
  choice

options:
  -h, --help  show this help message and exit
```

## rt alert

```text
usage: rt alert [-h] action ...

positional arguments:
  action
    list       open alerts
    show       one alert
    raise      raise an alert yourself
    resolve    close an alert
    set-level  change an alert's level

options:
  -h, --help   show this help message and exit
```

### rt alert list

```text
usage: rt alert list [-h] [--all]

options:
  -h, --help  show this help message and exit
  --all
```

### rt alert show

```text
usage: rt alert show [-h] id

positional arguments:
  id

options:
  -h, --help  show this help message and exit
```

### rt alert raise

```text
usage: rt alert raise [-h] [--description DESCRIPTION] [--evidence EVIDENCE]
                      [--files FILES] [--tasks TASKS]
                      {1,2,3,4,5} title

positional arguments:
  {1,2,3,4,5}
  title

options:
  -h, --help            show this help message and exit
  --description DESCRIPTION
  --evidence EVIDENCE
  --files FILES
  --tasks TASKS
```

### rt alert resolve

```text
usage: rt alert resolve [-h] id resolution

positional arguments:
  id
  resolution

options:
  -h, --help  show this help message and exit
```

### rt alert set-level

```text
usage: rt alert set-level [-h] id {1,2,3,4,5}

positional arguments:
  id
  {1,2,3,4,5}

options:
  -h, --help   show this help message and exit
```

## rt freeze

```text
usage: rt freeze [-h] [reason]

positional arguments:
  reason

options:
  -h, --help  show this help message and exit
```

## rt unfreeze

```text
usage: rt unfreeze [-h]

options:
  -h, --help  show this help message and exit
```

## rt config

```text
usage: rt config [-h] action ...

positional arguments:
  action
    show      all settings
    set       change one setting

options:
  -h, --help  show this help message and exit
```

### rt config show

```text
usage: rt config show [-h]

options:
  -h, --help  show this help message and exit
```

### rt config set

```text
usage: rt config set [-h] key value

positional arguments:
  key
  value

options:
  -h, --help  show this help message and exit
```

## rt export

```text
usage: rt export [-h]

options:
  -h, --help  show this help message and exit
```

## rt usage

```text
usage: rt usage [-h]

options:
  -h, --help  show this help message and exit
```

## rt setup

```text
usage: rt setup [-h] [--dry-run] [--remove] {claude-code,claude-app,codex}

positional arguments:
  {claude-code,claude-app,codex}

options:
  -h, --help            show this help message and exit
  --dry-run             show what would change
  --remove              remove Roundtable's entry
```

## rt launch

```text
usage: rt launch [-h] [--print] handle

positional arguments:
  handle

options:
  -h, --help  show this help message and exit
  --print     print the command instead of running it
```

## rt doctor

```text
usage: rt doctor [-h]

options:
  -h, --help  show this help message and exit
```

## rt watch

```text
usage: rt watch [-h] [--once] [--interval INTERVAL]

options:
  -h, --help           show this help message and exit
  --once
  --interval INTERVAL
```

## rt ui

```text
usage: rt ui [-h] [--port PORT] [--no-open]

options:
  -h, --help   show this help message and exit
  --port PORT
  --no-open
```

## rt mcp

```text
usage: rt mcp [-h]

options:
  -h, --help  show this help message and exit
```

## rt call

```text
usage: rt call [-h] op [params ...]

positional arguments:
  op
  params

options:
  -h, --help  show this help message and exit
```

## rt version

```text
usage: rt version [-h]

options:
  -h, --help  show this help message and exit
```

## Any operation: rt call

`rt call <operation> key=value ...` runs any operation directly. Human operations:

- `admin.config_set`: Change a setting
- `admin.config_show`: Show all settings
- `admin.export`: Write JSONL snapshots to .roundtable/export
- `admin.freeze`: Stop all seats until you unfreeze
- `admin.log`: History of events
- `admin.status`: Overview for the human
- `admin.unfreeze`: Let seats work again
- `admin.usage`: Context, tokens and plan limits per seat, plus Roundtable's own token cost
- `alert.set_level`: Change an alert's level
- `plan.amend_decide`: Approve (applies now) or reject an amendment
- `plan.cancel`: Cancel the active plan (and its unfinished tasks)
- `plan.continue`: Move on without missing drafts or critiques
- `plan.goal`: Start a plan for a goal
- `plan.lock`: Approve the plan and create its tasks (shows every proof command)
- `review.level_decide`: Approve or deny a request for deeper review
- `seat.add`: Register a model as a seat
- `seat.pause`: Pause a seat: its in-progress tasks return to ready
- `seat.release`: Free a seat whose chat was closed, so a new chat can join it
- `seat.remove`: Remove a seat (history is kept)
- `seat.resume`: Resume a paused seat
- `seat.worktree`: Create (or repair) a seat's working copy
- `task.cancel`: Cancel a task
- `task.merge`: Retry merging tasks waiting to merge
- `task.reassign`: Give a task to another seat (or none)
- `task.set_review`: Set one task's review depth
- `vote.decide`: Decide a vote (ties, or overrule)
