"""Database schema, version 1.

Conventions
- Times are UTC text from util.now(); ids are short strings (T3, A2, S7 ...)
  allocated with util.next_id, except events/leases/assignments (integers).
- JSON columns hold lists/objects as compact JSON text (util.jdump / jload).
- Never edit a released schema in place: add a migration in db.MIGRATIONS
  and bump SCHEMA_VERSION.

Task status values (see DESIGN.md for the state machine):
  open, ready, claimed, proving, in_review, changes_requested,
  merge_blocked, done, cancelled
"""

SCHEMA_VERSION = 1

SCHEMA_V1 = r"""
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
  kind TEXT PRIMARY KEY,
  next INTEGER NOT NULL
);

-- One model in one chat.
CREATE TABLE IF NOT EXISTS seats (
  handle          TEXT PRIMARY KEY,           -- 'opus'
  model           TEXT NOT NULL,              -- 'claude-opus-5-5' (passed to the app's --model)
  company         TEXT NOT NULL,              -- 'anthropic' | 'openai' | 'google' | ... (for cross-company review)
  app             TEXT NOT NULL,              -- claude-code | claude-app | codex-cli | codex-app | other
  roles           TEXT NOT NULL DEFAULT 'plan,build,review',
  status          TEXT NOT NULL DEFAULT 'active',   -- active | paused | removed
  worktree        TEXT,                       -- absolute path of this seat's working copy, or NULL
  branch          TEXT,                       -- 'rt/opus'
  session_key     TEXT,                       -- key handed out at join; NULL = no live chat
  session_started TEXT,
  last_seen       TEXT,
  bookmark        INTEGER NOT NULL DEFAULT 0, -- last event id this seat has seen in a digest
  now_doing       TEXT,                       -- one-line "now doing"
  created_at      TEXT NOT NULL
);

-- Append-only history. Every state change writes one event.
CREATE TABLE IF NOT EXISTS events (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  at       TEXT NOT NULL,
  actor    TEXT NOT NULL,                     -- seat handle, 'human' or 'system'
  type     TEXT NOT NULL,                     -- e.g. task.claimed, alert.raised (see DESIGN.md)
  ref      TEXT,                              -- main object id (T3, A2, P1 ...)
  task     TEXT,                              -- related task id, if any
  files    TEXT,                              -- JSON list of repo-relative paths/patterns
  audience TEXT,                              -- JSON list of seats this is FOR (shown in full); NULL = everyone (folded unless relevant)
  level    INTEGER NOT NULL DEFAULT 0,        -- alert level if relevant
  text     TEXT NOT NULL,                     -- one line, shown in digests
  data     TEXT                               -- JSON details
);
CREATE INDEX IF NOT EXISTS events_task ON events(task);

-- A plan for one goal. One active plan at a time.
CREATE TABLE IF NOT EXISTS plans (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  goal             TEXT NOT NULL,
  stage            TEXT NOT NULL,             -- drafting | critique | merging | proposed | voting | awaiting_human | locked | done | cancelled
  chair            TEXT,
  planners         TEXT NOT NULL DEFAULT '[]',-- JSON list of seat handles
  version          INTEGER NOT NULL DEFAULT 0,-- proposal version (0 = none yet)
  proposal_text    TEXT,                      -- merged plan text (<= draft_words)
  proposal_tasks   TEXT,                      -- JSON list of task specs (see DESIGN.md)
  revision_rounds  INTEGER NOT NULL DEFAULT 0,
  created_by       TEXT NOT NULL,
  created_at       TEXT NOT NULL,
  stage_changed_at TEXT NOT NULL,
  locked_at        TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
  id           TEXT PRIMARY KEY,              -- D1
  plan_id      INTEGER NOT NULL,
  author       TEXT NOT NULL,
  label        TEXT,                          -- 'A', 'B', 'C' (assigned when drafting closes; shown instead of author)
  text         TEXT NOT NULL,
  tasks        TEXT NOT NULL DEFAULT '[]',    -- JSON list of task specs
  submitted_at TEXT NOT NULL,
  UNIQUE(plan_id, author)
);

CREATE TABLE IF NOT EXISTS critiques (
  id           TEXT PRIMARY KEY,              -- K1
  plan_id      INTEGER NOT NULL,
  draft_id     TEXT NOT NULL,
  critic       TEXT NOT NULL,
  points       TEXT NOT NULL,                 -- JSON list of {verdict: keep|change|drop, text}
  submitted_at TEXT NOT NULL,
  UNIQUE(draft_id, critic)
);

-- Work handed to a seat (or to 'human'): critiques and reviews.
CREATE TABLE IF NOT EXISTS assignments (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  kind       TEXT NOT NULL,                   -- critique | review
  seat       TEXT NOT NULL,                   -- seat handle or 'human'
  target     TEXT NOT NULL,                   -- draft id (critique) or task id (review)
  round      INTEGER NOT NULL DEFAULT 1,
  status     TEXT NOT NULL DEFAULT 'open',    -- open | done | cancelled
  created_at TEXT NOT NULL,
  done_at    TEXT
);
CREATE INDEX IF NOT EXISTS assignments_seat ON assignments(seat, status);

CREATE TABLE IF NOT EXISTS approvals (
  plan_id  INTEGER NOT NULL,
  version  INTEGER NOT NULL,
  seat     TEXT NOT NULL,
  decision TEXT NOT NULL,                     -- approve | object
  reason   TEXT,
  at       TEXT NOT NULL,
  PRIMARY KEY (plan_id, version, seat)
);

-- Proposed changes to a locked plan.
CREATE TABLE IF NOT EXISTS amendments (
  id          TEXT PRIMARY KEY,               -- M1
  plan_id     INTEGER NOT NULL,
  proposed_by TEXT NOT NULL,
  kind        TEXT NOT NULL,                  -- add_task | edit_task | change_proof | change_owner | cancel_task | change_files
  task        TEXT,
  payload     TEXT NOT NULL,                  -- JSON
  reason      TEXT,
  status      TEXT NOT NULL DEFAULT 'pending',-- pending | applied | rejected
  needs       TEXT NOT NULL DEFAULT '[]',     -- JSON list of approvers still needed (seat handles and/or 'human')
  created_at  TEXT NOT NULL,
  decided_at  TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  id              TEXT PRIMARY KEY,           -- T1, T1.1
  plan_id         INTEGER,
  parent          TEXT,
  seq             INTEGER NOT NULL DEFAULT 0, -- display order
  title           TEXT NOT NULL,
  summary         TEXT NOT NULL DEFAULT '',   -- L1 (<= summary_words)
  detail          TEXT NOT NULL DEFAULT '',   -- L2 text
  owner           TEXT,                       -- planned / current owner seat
  status          TEXT NOT NULL,
  risk            TEXT NOT NULL DEFAULT 'normal', -- low | normal | high
  files           TEXT NOT NULL DEFAULT '[]', -- JSON list of patterns this task may edit
  proof           TEXT NOT NULL DEFAULT '[]', -- JSON list of shell commands (approved by the human at lock)
  review_override TEXT,                       -- low | mid | high | NULL
  review_round    INTEGER NOT NULL DEFAULT 0,
  base_commit     TEXT,                       -- seat branch commit when claimed
  commit_sha      TEXT,                       -- commit that passed proof
  merge_commit    TEXT,
  claimed_at      TEXT,
  closed_at       TEXT,                       -- last close (proof start)
  done_at         TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner);

CREATE TABLE IF NOT EXISTS deps (
  task       TEXT NOT NULL,
  depends_on TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'blocks',  -- blocks | related
  PRIMARY KEY (task, depends_on)
);

CREATE TABLE IF NOT EXISTS leases (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  pattern     TEXT NOT NULL,                  -- repo-relative path or glob
  seat        TEXT NOT NULL,
  task        TEXT,
  state       TEXT NOT NULL DEFAULT 'active', -- active | released | expired
  acquired_at TEXT NOT NULL,
  renewed_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL,
  ended_at    TEXT
);
CREATE INDEX IF NOT EXISTS leases_active ON leases(state, seat);

-- File holds from level-4 (hold) and level-5 (freeze) alerts.
CREATE TABLE IF NOT EXISTS holds (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  pattern  TEXT NOT NULL,
  alert_id TEXT NOT NULL,
  kind     TEXT NOT NULL,                     -- hold | freeze
  active   INTEGER NOT NULL DEFAULT 1,
  at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
  id         TEXT PRIMARY KEY,                -- C1
  task       TEXT NOT NULL,
  seat       TEXT NOT NULL,
  l0         TEXT NOT NULL,                   -- one line
  l1         TEXT NOT NULL,                   -- <= summary_words
  commit_sha TEXT,
  files      TEXT NOT NULL DEFAULT '[]',
  added      INTEGER NOT NULL DEFAULT 0,
  removed    INTEGER NOT NULL DEFAULT 0,
  at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proof_runs (
  id          TEXT PRIMARY KEY,               -- PR1
  task        TEXT NOT NULL,
  seat        TEXT NOT NULL,
  commands    TEXT NOT NULL,                  -- JSON list
  status      TEXT NOT NULL,                  -- queued | running | passed | failed | timeout | error
  exit_code   INTEGER,
  failed_cmd  TEXT,
  output_tail TEXT,
  commit_sha  TEXT,
  workdir     TEXT NOT NULL,
  pid         INTEGER,
  started_at  TEXT,
  finished_at TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id           TEXT PRIMARY KEY,              -- R1
  task         TEXT NOT NULL,
  reviewer     TEXT NOT NULL,                 -- seat handle or 'human'
  level        TEXT NOT NULL,                 -- low | mid | high (level used)
  round        INTEGER NOT NULL,
  verdict      TEXT NOT NULL DEFAULT 'pending', -- pending | approve | changes
  points       TEXT NOT NULL DEFAULT '[]',
  est_tokens   INTEGER NOT NULL DEFAULT 0,    -- characters handed to the reviewer / 4
  created_at   TEXT NOT NULL,
  submitted_at TEXT
);

CREATE TABLE IF NOT EXISTS line_comments (
  id          TEXT PRIMARY KEY,               -- L1
  review_id   TEXT NOT NULL,
  task        TEXT NOT NULL,
  file        TEXT NOT NULL,
  line        INTEGER,
  text        TEXT NOT NULL,
  resolved    INTEGER NOT NULL DEFAULT 0,
  reply       TEXT,
  resolved_by TEXT,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS suggestions (
  id         TEXT PRIMARY KEY,                -- S1
  from_seat  TEXT NOT NULL,
  to_seat    TEXT NOT NULL,
  task       TEXT,
  file       TEXT,
  text       TEXT NOT NULL,
  patch      TEXT,
  status     TEXT NOT NULL DEFAULT 'open',    -- open | accepted | rejected | later
  reply      TEXT,
  created_at TEXT NOT NULL,
  replied_at TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
  id             TEXT PRIMARY KEY,            -- A1
  level          INTEGER NOT NULL,            -- 1..5
  title          TEXT NOT NULL,
  description    TEXT NOT NULL DEFAULT '',
  evidence       TEXT NOT NULL DEFAULT '',
  files          TEXT NOT NULL DEFAULT '[]',
  tasks          TEXT NOT NULL DEFAULT '[]',
  must_ack       TEXT NOT NULL DEFAULT '[]',  -- JSON list of seats that must acknowledge
  raised_by      TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'open',-- open | acknowledged | resolved
  proposed_level INTEGER,
  proposed_by    TEXT,
  created_at     TEXT NOT NULL,
  resolved_at    TEXT,
  resolved_by    TEXT,
  resolution     TEXT
);

CREATE TABLE IF NOT EXISTS alert_acks (
  alert_id TEXT NOT NULL,
  seat     TEXT NOT NULL,
  at       TEXT NOT NULL,
  PRIMARY KEY (alert_id, seat)
);

CREATE TABLE IF NOT EXISTS votes (
  id         TEXT PRIMARY KEY,                -- V1
  topic      TEXT NOT NULL,
  options    TEXT NOT NULL,                   -- JSON list of option strings
  kind       TEXT NOT NULL DEFAULT 'general', -- general | plan | review
  ref        TEXT,                            -- plan id / task id this decides
  opened_by  TEXT NOT NULL,
  voters     TEXT NOT NULL,                   -- JSON list of seats expected to vote
  status     TEXT NOT NULL DEFAULT 'open',    -- open | decided | tied
  result     TEXT,
  decided_by TEXT,                            -- 'majority' | 'human'
  created_at TEXT NOT NULL,
  decided_at TEXT
);

CREATE TABLE IF NOT EXISTS ballots (
  vote_id TEXT NOT NULL,
  seat    TEXT NOT NULL,
  choice  TEXT NOT NULL,
  reason  TEXT,
  at      TEXT NOT NULL,
  PRIMARY KEY (vote_id, seat)
);

-- A seat asking the human for a deeper review on one task.
CREATE TABLE IF NOT EXISTS level_requests (
  id         TEXT PRIMARY KEY,                -- Q1
  task       TEXT NOT NULL,
  seat       TEXT NOT NULL,
  level      TEXT NOT NULL,
  reason     TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'pending', -- pending | approved | denied
  created_at TEXT NOT NULL,
  decided_at TEXT
);

-- Background wake-up runs started by the watcher (rate limiting + audit).
CREATE TABLE IF NOT EXISTS wakeups (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  seat     TEXT NOT NULL,
  reason   TEXT NOT NULL,
  ref      TEXT,
  pid      INTEGER,
  at       TEXT NOT NULL
);

-- Every MCP call a seat makes: what talking to Roundtable costs (chars / 4 ~ tokens).
CREATE TABLE IF NOT EXISTS exchange (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  at        TEXT NOT NULL,
  seat      TEXT NOT NULL,
  op        TEXT NOT NULL,
  chars_in  INTEGER NOT NULL,
  chars_out INTEGER NOT NULL,
  ok        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS exchange_seat ON exchange(seat, at);

-- Notifications already sent to the human (so the watcher never repeats one).
CREATE TABLE IF NOT EXISTS notices (
  key TEXT PRIMARY KEY,
  at  TEXT NOT NULL
);
"""
