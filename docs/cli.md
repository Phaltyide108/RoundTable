# Command reference

Generated from the code by `scripts/gen_docs.py`. Every command also accepts the global options below.

```text
usage: rt [-h] [--version] [--home HOME] [--seat AS_SEAT] [--key SEAT_KEY]
          [--json]
          command ...

Roundtable: AI models planning, building and reviewing one project together. Easiest: rt ui opens the dashboard, where every command below is a button.

positional arguments:
  command
    init          set up Roundtable in this project
    status        overview: plan, seats, tasks, what waits on you
    log           history of events
    seat          manage seats (models)
    goal          start a plan
    plan          the plan
    task          tasks
    memory        project memory every model sees when it joins
    compact       shrink history of work finished long ago
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
    run           run a seat in the background: Roundtable starts its app
                  whenever it has work
    bench         does a team do better than one AI? same task, hidden tests
    doctor        check everything and suggest fixes
    watch         notify you and wake seats when needed
    ask           ask the table: every AI answers, they rank each other's
                  answers without names, the best writes the final answer
    app           open Roundtable in its own window (--install adds it to your
                  app menu)
    ui            the same as rt app: Roundtable in its own window
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

commands by purpose:
  start here        app (or ui), init, status, doctor
  models            seat (add, set, list, pause, resume, release, remove), launch, run, setup
  plan and work     ask, goal, plan, task (list, show, file, accept, edit, link, ...), review, memory
  problems          alert, vote, freeze, unfreeze
  follow along      log, usage, watch, export, compact, config, bench
  for apps          mcp, call
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
    set       change a seat's model or thinking effort
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
usage: rt seat add [-h] --model MODEL --app
                   {claude-code,claude-vscode,claude-app,codex-cli,codex-vscode,codex-app,gemini-cli,qwen-code,opencode,copilot-cli,cursor,other}
                   [--company COMPANY] [--roles ROLES] [--no-worktree]
                   handle

positional arguments:
  handle

options:
  -h, --help            show this help message and exit
  --model MODEL         model id the app understands, e.g. claude-opus-5-5
  --app {claude-code,claude-vscode,claude-app,codex-cli,codex-vscode,codex-app,gemini-cli,qwen-code,opencode,copilot-cli,cursor,other}
                        claude-code: Claude Code in a terminal; claude-vscode:
                        Claude Code in VS Code; claude-app: Claude desktop app
                        (plans and reviews only); codex-cli: Codex in a
                        terminal; codex-vscode: Codex in VS Code; codex-app:
                        ChatGPT desktop app (Codex mode); gemini-cli: Gemini
                        CLI in a terminal; qwen-code: Qwen Code in a terminal;
                        opencode: opencode in a terminal; copilot-cli: GitHub
                        Copilot CLI in a terminal; cursor: Cursor editor;
                        other: Another app that supports MCP
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

### rt seat set

```text
usage: rt seat set [-h] [--model MODEL] [--effort EFFORT] handle

positional arguments:
  handle

options:
  -h, --help       show this help message and exit
  --model MODEL
  --effort EFFORT  claude-code: low|medium|high|xhigh|max; codex-cli:
                   minimal|low|medium|high|xhigh|max|ultra; opencode: the
                   model's variants; default clears it
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
usage: rt goal [-h] [--planners PLANNERS] [--review {low,mid,high}] [--quick]
               [--auto]
               goal

positional arguments:
  goal

options:
  -h, --help            show this help message and exit
  --planners PLANNERS   comma list of seats
  --review {low,mid,high}
  --quick               skip the planning rounds: one AI splits the goal into
                        tasks
  --auto                start building without waiting for your approval
```

## rt plan

```text
usage: rt plan [-h] action ...

positional arguments:
  action
    view        show the plan
    continue    move on without missing drafts/critiques
    lock        approve the plan; creates tasks
    cancel      cancel the active plan
    amend-decide
                approve or reject an amendment

options:
  -h, --help    show this help message and exit
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
    show        show a task
    cancel      cancel a task
    reassign    give a task to another seat
    merge       retry merges
    review-level
                set one task's review depth
    list        list tasks, most urgent first
    file        add work to the backlog (ready at once if you give files and a
                test command)
    accept      turn a backlog item into work
    edit        change title, kind, priority, labels, summary, files or test
                command
    link        TASK waits_for|related|discovered_from|parent OTHER

options:
  -h, --help    show this help message and exit
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

### rt task list

```text
usage: rt task list [-h] [--status STATUS]
                    [--kind {task,feature,bug,chore,docs,test,epic}]
                    [--label LABEL] [--priority {0,1,2,3,4}] [--owner OWNER]
                    [--limit LIMIT]

options:
  -h, --help            show this help message and exit
  --status STATUS       backlog, open, ready, working, review, done, all
  --kind {task,feature,bug,chore,docs,test,epic}
  --label LABEL
  --priority {0,1,2,3,4}
                        this priority or more urgent (0 urgent .. 4 someday)
  --owner OWNER
  --limit LIMIT
```

### rt task file

```text
usage: rt task file [-h] [--kind {task,feature,bug,chore,docs,test,epic}]
                    [--priority {0,1,2,3,4}] [--summary SUMMARY]
                    [--files FILES] [--proof PROOF] [--parent PARENT]
                    [--labels LABELS]
                    title

positional arguments:
  title

options:
  -h, --help            show this help message and exit
  --kind {task,feature,bug,chore,docs,test,epic}
  --priority {0,1,2,3,4}
  --summary SUMMARY
  --files FILES         comma list
  --proof PROOF         test command (repeatable)
  --parent PARENT       epic task id
  --labels LABELS       comma list
```

### rt task accept

```text
usage: rt task accept [-h] [--files FILES] [--proof PROOF] [--owner OWNER]
                      [--priority {0,1,2,3,4}]
                      task

positional arguments:
  task

options:
  -h, --help            show this help message and exit
  --files FILES         comma list (default: as filed)
  --proof PROOF         test command (repeatable; default: as filed)
  --owner OWNER
  --priority {0,1,2,3,4}
```

### rt task edit

```text
usage: rt task edit [-h] [--title TITLE]
                    [--kind {task,feature,bug,chore,docs,test,epic}]
                    [--priority {0,1,2,3,4}] [--labels LABELS]
                    [--summary SUMMARY] [--files FILES] [--proof PROOF]
                    task

positional arguments:
  task

options:
  -h, --help            show this help message and exit
  --title TITLE
  --kind {task,feature,bug,chore,docs,test,epic}
  --priority {0,1,2,3,4}
  --labels LABELS       comma list (replaces)
  --summary SUMMARY
  --files FILES         comma list
  --proof PROOF         test command (repeatable)
```

### rt task link

```text
usage: rt task link [-h] [--remove]
                    task {waits_for,related,discovered_from,parent} other

positional arguments:
  task
  {waits_for,related,discovered_from,parent}
  other

options:
  -h, --help            show this help message and exit
  --remove
```

## rt memory

```text
usage: rt memory [-h] action ...

positional arguments:
  action
    add       remember something (yours are pinned)
    list      show project memory
    forget    forget a note
    pin       pin a note
    unpin     unpin a note

options:
  -h, --help  show this help message and exit
```

### rt memory add

```text
usage: rt memory add [-h] [--tags TAGS] text

positional arguments:
  text

options:
  -h, --help   show this help message and exit
  --tags TAGS  comma list
```

### rt memory list

```text
usage: rt memory list [-h] [--all] [query]

positional arguments:
  query

options:
  -h, --help  show this help message and exit
  --all
```

### rt memory forget

```text
usage: rt memory forget [-h] [--reason REASON] id

positional arguments:
  id

options:
  -h, --help       show this help message and exit
  --reason REASON
```

### rt memory pin

```text
usage: rt memory pin [-h] id

positional arguments:
  id

options:
  -h, --help  show this help message and exit
```

### rt memory unpin

```text
usage: rt memory unpin [-h] id

positional arguments:
  id

options:
  -h, --help  show this help message and exit
```

## rt compact

```text
usage: rt compact [-h] [--days DAYS]

options:
  -h, --help   show this help message and exit
  --days DAYS
```

## rt review

```text
usage: rt review [-h] action ...

positional arguments:
  action
    queue       reviews waiting for you
    get         read a task for review
    submit      approve or request changes
    level-decide
                approve/deny a deeper-review request

options:
  -h, --help    show this help message and exit
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
    list      open alerts
    show      one alert
    raise     raise an alert yourself
    resolve   close an alert
    set-level
              change an alert's level

options:
  -h, --help  show this help message and exit
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
usage: rt setup [-h] [--dry-run] [--remove]
                {claude-code,claude-app,codex,copilot}

positional arguments:
  {claude-code,claude-app,codex,copilot}

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

## rt run

```text
usage: rt run [-h] [--once] [--stop] [--detach] handle

positional arguments:
  handle

options:
  -h, --help  show this help message and exit
  --once      do the waiting work once, then stop
  --stop      stop the seat's background runner
  --detach    start it as its own process and return
```

## rt bench

```text
usage: rt bench [-h] action ...

positional arguments:
  action
    list      benchmark tasks
    run       run each contender on a task, then score them with hidden tests
    score     score a folder against a task's hidden tests

options:
  -h, --help  show this help message and exit
```

### rt bench list

```text
usage: rt bench list [-h]

options:
  -h, --help  show this help message and exit
```

### rt bench run

```text
usage: rt bench run [-h] [--task TASK] [--solo SOLO] [--team TEAM]
                    [--vote VOTE] [--mode {quick,full}]
                    [--review {low,mid,high}] [--minutes MINUTES] [--out OUT]
                    [--seed SEED]

options:
  -h, --help            show this help message and exit
  --task TASK
  --solo SOLO           an AI alone: claude, codex, claude:high,
                        codex:gpt-6.1-sol:xhigh (repeatable)
  --team TEAM           a team, comma separated: claude,codex (repeatable)
  --vote VOTE           quiz tasks: one AI answers several times on its own
                        and the most common answer wins, e.g.
                        codex:gpt-6.1-sol:low*3 (repeatable)
  --mode {quick,full}   how the team plans (default quick)
  --review {low,mid,high}
                        how carefully the team checks itself
  --minutes MINUTES     time limit per contender
  --out OUT             folder for the work and the report (default
                        ./roundtable-bench/<time>)
  --seed SEED           generated tasks (fresh): repeat the problems of an
                        earlier run
```

### rt bench score

```text
usage: rt bench score [-h] [--task TASK] folder

positional arguments:
  folder

options:
  -h, --help   show this help message and exit
  --task TASK
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

## rt ask

```text
usage: rt ask [-h] [--seats SEATS] [--follow-up FOLLOW_UP] [--no-wait]
              [--show ID] [--all] [--list] [--cancel ID]
              [question]

positional arguments:
  question              what you want to know (the AIs can read the project
                        but change nothing)

options:
  -h, --help            show this help message and exit
  --seats SEATS         comma list of who answers (default: every AI
                        Roundtable can run)
  --follow-up FOLLOW_UP
                        the id of an earlier question this one follows, e.g.
                        Q2
  --no-wait             start it and return; see it later with rt ask --show
                        Q1
  --show ID             show a question: the final answer and how they ranked
                        each other
  --all                 with --show: every answer and review in full
  --list                questions asked so far
  --cancel ID           stop a question that is still being answered
```

## rt app

```text
usage: rt app [-h] [--port PORT] [--browser] [--foreground] [--install]
              [--uninstall]

options:
  -h, --help    show this help message and exit
  --port PORT
  --browser     open it in your web browser instead of its own window
  --foreground  keep this terminal attached until the window closes
  --install     add Roundtable to your app menu (Linux, macOS, Windows)
  --uninstall   take it out of the app menu again
```

## rt ui

```text
usage: rt ui [-h] [--port PORT] [--browser] [--no-open]

options:
  -h, --help   show this help message and exit
  --port PORT
  --browser    open it in your web browser instead of its own window
  --no-open    only start the dashboard server
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

- `admin.compact`: Shrink old history: keep each finished task's outcome, drop step-by-step detail
- `admin.config_set`: Change a setting
- `admin.config_show`: Show all settings
- `admin.export`: Write JSONL snapshots to .roundtable/export
- `admin.freeze`: Stop all seats until you unfreeze
- `admin.log`: History of events
- `admin.status`: Overview for the human
- `admin.unfreeze`: Let seats work again
- `admin.usage`: Context, tokens and plan limits per seat, plus Roundtable's own token cost
- `alert.set_level`: Change an alert's level
- `council.ask`: Ask the table: every chosen AI answers on its own, they rank each other's answers without names, and the best writes the final answer
- `council.cancel`: Stop a question that is still being answered
- `council.list`: Questions asked to the table, newest first
- `council.show`: A question to the table: the final answer, how they ranked each other, and every answer
- `memory.pin`: Pin a note so every seat sees it when it joins (or unpin it)
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
- `seat.set`: Change a seat's model or how hard it thinks (takes effect the next time it starts)
- `seat.worktree`: Create (or repair) a seat's working copy
- `task.accept`: Turn a backlog item into work (its files and test command are final here)
- `task.cancel`: Cancel a task
- `task.edit`: Change a task's title, kind, priority, labels, summary, files or test command
- `task.merge`: Retry merging tasks waiting to merge
- `task.reassign`: Give a task to another seat (or none)
- `task.set_review`: Set one task's review depth
- `vote.decide`: Decide a vote (ties, or overrule)
