# Benchmarks: does a team do better than one AI?

Every run below used `rt bench`, on one Linux computer, with real Claude Code and Codex logins (no API keys). Each contender gets the same written specification in a fresh git repository; hidden tests it never saw are run against what it built, in a copy of its folder. A team is scored on what is merged into its main branch when the plan is done or the time limit is reached.

Run them yourself: `rt bench run --task sheet` or `rt bench run --task sql`, and `rt bench score FOLDER --task sql` for any folder.

## The tasks

| Task | What it asks | Hidden tests | How they are checked |
| --- | --- | --- | --- |
| `sheet` | A spreadsheet engine: formulas with precedence, ranges, functions, errors that spread, cycles, recalculation | 52 | Expected values written by hand |
| `sql` | A SQL engine (CREATE, INSERT, SELECT with joins, GROUP BY, HAVING, ORDER BY, LIMIT, UPDATE, DELETE) that must give exactly SQLite's answers: NULL logic, integer division, `%` with reals, type affinity on insert, mixed-type ordering, `||` binding tighter than `*` | 111 | Every query runs on real SQLite too; answers must match, int versus real included. Code that hands the work to `sqlite3` scores 0 |

## Results

All runs: default thinking effort (Claude Code's default; Codex's `xhigh` from the user's config), team planning `quick`, team checking `mid`.

| Date | Task | Contender | Hidden tests | Minutes | Tokens | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-14 | sheet | Claude Opus 5.5 alone | 52/52 | 6.5 | 99,034 | |
| 2026-10-14 | sheet | GPT-6.1 Sol alone | 52/52 | 20.7 | 91,968 | |
| 2026-10-14 | sheet | Team: Opus + Sol | 0/52 merged; 52/52 unmerged | 40 (limit) | 138,798 | Opus built it in 5 min and its tests passed; Sol's review (2.5 min) asked for 4 fixes beyond the hidden tests; then Claude's 5-hour plan limit ran out, so the fixes never landed and nothing was merged. Led to the usage-limit handoff (below). |
| 2026-10-14 | sql | GPT-6.1 Sol alone | 111/111 | 19.0 | 104,019 | |
| 2026-10-14 | sql | Claude Opus 5.5 alone | 111/111 | 27.9 | 422,923 | Already 111/111 at minute 22; kept checking its own edge cases |
| 2026-10-14 | sql | GPT-6 Luna (low thinking) alone | 110/111 | 2.3 | 78,823 | Missed one rule: a trailing `;` is allowed |

Token counts are new tokens (input not read from cache, plus output) as the apps reported them.

## What we learned

1. **On a clear specification of this size, a top model alone gets everything right.** Both Claude Opus 5.5 and GPT-6.1 Sol passed every hidden test of both tasks. A team cannot be more accurate than 100%; it can only cost more, because the other model reads and tests the work.
2. **The reviewer found real issues anyway.** In the sheet run, Sol asked for four changes the hidden tests did not cover. Whether that matters depends on what you are building; for a product, it is the point of review.
3. **A team survives what stops a single AI.** The team run stalled because Claude ran out of usage, a limit any single-model setup also hits. Roundtable now recognises "you've hit your limit · resets 9:20pm", stops retrying until then, and hands that AI's unfinished tasks to the others, whose branch starts from its work, and its reviews to another reviewer.
4. **Planning shape matters for speed.** The quick planner made the second AI's test-writing task wait for the first AI's code, so it sat idle for the first minutes. Quick plans are now told to let independent work run in parallel.

## Next

The cases where a team should beat one AI are the ones where a single model makes mistakes: smaller and cheaper models, vague goals, large existing codebases, and long multi-part work. The benchmark accepts any model and effort, e.g.

```bash
rt bench run --task sql --solo claude:claude-haiku-5-5:low --solo codex:gpt-6-luna:low --team claude:claude-haiku-5-5:low,codex:gpt-6-luna:low
```
