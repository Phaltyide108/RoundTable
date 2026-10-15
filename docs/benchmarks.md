# Benchmarks: does a team do better than one AI?

Every run below used `rt bench`, on one Linux computer, with real Claude Code and Codex logins (no API keys). Each contender gets the same written specification in a fresh git repository; hidden tests it never saw are run against what it built, in a copy of its folder. A team is scored on what is merged into its main branch when the plan is done or the time limit is reached.

Run them yourself: `rt bench run --task sheet` or `rt bench run --task sql`, and `rt bench score FOLDER --task sql` for any folder.

## The tasks

| Task | What it asks | Hidden tests | How they are checked |
| --- | --- | --- | --- |
| `sheet` | A spreadsheet engine: formulas with precedence, ranges, functions, errors that spread, cycles, recalculation | 52 | Expected values written by hand |
| `pond` | A living 3D koi pond in three.js: a wave-equation water surface (ripples spread, reflect, fade; clicks make them), at least 15 koi schooling with boids rules, food they chase and eat, lily pads riding the waves | 25 | Run in headless Chrome: checks through a small `window.pond` test interface (fish stay inside, keep apart, align, chase food; ripples rise, spread, fade; lily pads follow the water), plus script errors, a real picture, window resizes. A screenshot of each contender's pond is saved next to the report |
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
| 2026-10-14 | sql | Team: Opus + Sol | 0/111 merged | 45 (limit) | 218,429 | Claude ran out of usage 2 minutes in; its planned tasks stayed reserved for it, so Sol finished its own tasks and waited. Led to handing over planned tasks too. |
| 2026-10-15 | sql | Claude Haiku 5.5 (low thinking) alone | 111/111 | 4.7 | | Even the smallest Claude model gets this specification fully right alone |
| 2026-10-15 | sql | Team: Haiku + Luna (low) | stopped | | | All five tasks started at once and each proof ran the whole suite, so none could pass before the others merged; stopped and fixed (each task now tests only its part and depends on what it imports) |
| 2026-10-15 | pond | GPT-6 Luna (low thinking) alone | 14/25 | 1.4 | 54,816 | Looks good at a glance, but its water is a square sheet sticking out of the round pond, and its simulation turns to NaN (fish, waves, food all break) |
| 2026-10-15 | pond | Claude Haiku 5.5 (low thinking) alone | 25/25 | 5.0 | | |
| 2026-10-15 | pond | Team: Haiku + Luna (low) | 25/25 | 6.4 | 614,364 | Six tasks split across both; the team's result has none of Luna's failures. A person looking at it: works, with a jagged edge where the water meets the wall |

Token counts are new tokens (input not read from cache, plus output) as the apps reported them.

## What we learned

1. **On a clear specification of this size, a top model alone gets everything right.** Both Claude Opus 5.5 and GPT-6.1 Sol passed every hidden test of both tasks. A team cannot be more accurate than 100%; it can only cost more, because the other model reads and tests the work.
2. **The reviewer found real issues anyway.** In the sheet run, Sol asked for four changes the hidden tests did not cover. Whether that matters depends on what you are building; for a product, it is the point of review.
3. **A team survives what stops a single AI.** The team run stalled because Claude ran out of usage, a limit any single-model setup also hits. Roundtable now recognises "you've hit your limit · resets 9:20pm", stops retrying until then, and hands that AI's unfinished tasks to the others, whose branch starts from its work, and its reviews to another reviewer.
4. **Planning shape matters for speed.** The quick planner made the second AI's test-writing task wait for the first AI's code, so it sat idle for the first minutes. Quick plans are now told to let independent work run in parallel.

5. **A team is as good as its best member, and much better than its weakest.** On the pond, Luna alone broke (its simulation turned into NaN; the owner, clicking the water, saw it "go dry"), Haiku alone passed everything, and the two together passed everything. That is a real gain over Luna, not over Haiku, and it cost about ten times Luna's tokens.

## Next

The cases where a team should beat one AI are the ones where a single model makes mistakes: smaller and cheaper models, vague goals, large existing codebases, and long multi-part work. The benchmark accepts any model and effort, e.g.

```bash
rt bench run --task sql --solo claude:claude-haiku-5-5:low --solo codex:gpt-6-luna:low --team claude:claude-haiku-5-5:low,codex:gpt-6-luna:low
```
