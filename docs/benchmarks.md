# Benchmarks: does a team do better than one AI?

Every run below used `rt bench`, on one Linux computer, with real Claude Code and Codex logins (no API keys). Each contender gets the same written specification in a fresh git repository; hidden tests it never saw are run against what it built, in a copy of its folder. A team is scored on what is merged into its main branch when the plan is done or the time limit is reached.

Run them yourself: `rt bench run --task sheet` or `rt bench run --task sql`, and `rt bench score FOLDER --task sql` for any folder.

## The tasks

| Task | What it asks | Hidden tests | How they are checked |
| --- | --- | --- | --- |
| `sheet` | A spreadsheet engine: formulas with precedence, ranges, functions, errors that spread, cycles, recalculation | 52 | Expected values written by hand |
| `pond` | A living 3D koi pond in three.js: a wave-equation water surface (ripples spread, reflect, fade; clicks make them), at least 15 koi schooling with boids rules, food they chase and eat, lily pads riding the waves | 25 | Run in headless Chrome: checks through a small `window.pond` test interface (fish stay inside, keep apart, align, chase food; ripples rise, spread, fade; lily pads follow the water), plus script errors, a real picture, window resizes. A screenshot of each contender's pond is saved next to the report |
| `pondpro` | The pond measured against exact physics: waves at 2.0 m/s, amplitude halving every 3 s, stable under 60 strong ripples, fish 0.4 m apart turning at most 3 rad/s, stones, a heron they flee, pellets that float 2 s then sink at 0.25 m/s, 200 fish fast enough, seeded determinism | 32 | Same as `pond`, with each number measured within a tolerance |
| `quiz` | 30 tricky questions with exact answers (counting traps, modular arithmetic, clock angles, letter counting) | 30 | Exact answers. One AI alone answers in one read-only run; a team answers by asking the table |
| `quizhard` | 30 competition-style questions (inclusion-exclusion, derangements, base-12 trailing zeros, chord regions, ...) | 30 | Every answer computed by a program |
| `aime` | The 30 problems of AIME 2025, tools off | 30 | Published answers. **Not a fair test:** the models have seen it (see below) |
| `fresh` | 20 hard competition-style problems made up from a seed for each run (towers of powers, Lucas' theorem, digit counting with divisibility, order-3 recurrences out to 10^15, 12-person seatings with forbidden pairs, necklaces, ...), tools off | 20 | Every answer computed by a program and checked a second way in the tests; `--seed N` repeats a set |
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
| 2026-10-15 | sql | Team: Haiku + Luna (low), after the fix | 111/111 | 9.7 | 552,242 | Luna's missed rule (the trailing `;`) is not in the team's result |
| 2026-10-15 | pond | GPT-6 Luna (low thinking) alone | 14/25 | 1.4 | 54,816 | Looks good at a glance, but its water is a square sheet sticking out of the round pond, and its simulation turns to NaN (fish, waves, food all break) |
| 2026-10-15 | pond | Claude Haiku 5.5 (low thinking) alone | 25/25 | 5.0 | | |
| 2026-10-15 | pond | Team: Haiku + Luna (low) | 25/25 | 6.4 | 614,364 | Six tasks split across both; the team's result has none of Luna's failures. A person looking at it: works, with a jagged edge where the water meets the wall |
| 2026-10-15 | pondpro | Claude Haiku 5.5 (low) alone | 31/32 | 8.1 | 234,731 | Missed only "fleeing fish speed up past 2 m/s" (the spec said "up to 3 m/s"; now explicit) |
| 2026-10-15 | pondpro | GPT-6 Luna (low) alone | 26/32 | 1.2 | 38,640 | Fish turn instantly (187 rad/s, limit 3) and barely school; waves too slow (2.65 s to 4 m) and fade too slowly; the water blows up to 7.5 m waves; fleeing not faster |
| 2026-10-15 | pondpro | Team: Haiku + Luna (low) | 31/32 | 9.9 | 803,364 | None of Luna's six failures; the same fleeing-speed miss as Haiku |
| 2026-10-15 | quiz | Claude Haiku 5.5 (low) alone | 30/30 | 0.2 | 12,958 | |
| 2026-10-15 | quiz | GPT-6 Luna (low) alone | 23/30 | 0.3 | 3,868 | |
| 2026-10-15 | quiz | Team (asking the table) | 30/30 | 0.6 | 51,929 | |
| 2026-10-15 | quizhard | Haiku alone / Luna alone / team, first council | 29 / 26 / 29 | | 28k / 19k / 100k | Luna had Q14 right, Haiku wrong; the team kept Haiku's wrong answer. Led to the two council changes below |
| 2026-10-15 | quizhard | Haiku alone, 3 runs | 28, 29, 29 | 0.3-0.5 | ~16k each | |
| 2026-10-15 | quizhard | Luna alone, 3 runs | 17, 17, 18 | 0.1 | 2-5k each | |
| 2026-10-15 | quizhard | **Team, 3 runs** | **30, 30, 30** | ~2 | ~76k each | Better than its best member in every run |

Token counts are new tokens (input not read from cache, plus output) as the apps reported them.

## Does combining models raise the score? (fresh problems, tools off)

The question: on problems a single model sometimes gets wrong, does a team of models get more right than its best member, and is that worth the cost?

### How this was measured

- **Problems nobody has seen.** Published sets are in the models' training data: on AIME 2025, Claude Haiku 5.5 at low thinking with every tool off scored 30/30 and wrote that it recalled two answers "from memory of the published answers". So `fresh` makes 20 new problems from a seed for every run, with large numbers that make counting by hand hopeless; each needs the right idea carried out without a slip. Every answer is computed by a program.
- **Tools off, the same for everyone.** No code, no web, no files. (An earlier version let Codex keep a read-only shell; GPT-6.1 Sol found this by reading the code. The traces of every Codex run show no commands and no file reads, so the results below stand, and the gap is now closed: Codex runs with its shell, browser, web search and MCP off, in an empty folder, and the answers are not on disk during a run.)
- **Every member scored inside the team.** In a council each model writes its own answer first, without seeing the others. Those answers are scored too, so a team's final answer is compared with its own members on the same problems in the same run.
- **The baseline a council must beat:** one model answering three times on its own with a majority vote (`--vote`), at a similar cost.

### Results

Each row is one set of 20 problems; each set has different problems.

| Set | Contender | Final | Each member on its own | Tokens |
| --- | --- | --- | --- | --- |
| 101 | Claude Haiku 5.5 (low) alone | 19 | | |
| 101 | GPT-6 Luna (low) alone | 0 | refused: "I can't provide a reliable set of 20 answers under the no tools constraint" | 14k |
| 101 | Team: Haiku (low) + Luna (low) | 18 | Haiku 18, Luna 0 (guessed every answer) | 102k |
| 102 | Team: Haiku (low) + Luna (low) | 18 | Haiku 16, Luna 0 | 134k |
| 103 | Team: Haiku (low) + Luna (low) | 18 | Haiku 18, Luna 0 | 116k |
| 201-203 | GPT-6.1 Sol (low) alone (Haiku could not start: Claude's weekly limit) | 19, 17, 20 | | 18k each |
| 301 | Sol (low) alone | 20 | | 23k |
| 301 | Sol (low) × 3, majority vote | 20 | 20, 17, 20 | 74k |
| 301 | Council: Sol (low) + Sol (low) | 20 | 17, 20 | 116k |
| 302 | Sol (low) alone | 18 | | 9k |
| 302 | Sol (low) × 3, majority vote | 20 | 20, 20, 19 | 91k |
| 302 | Council: Sol (low) + Sol (low) | **20** | **15, 16** | 115k |
| 303 | Sol (low) alone | 20 | | 13k |
| 303 | Sol (low) × 3, majority vote | 20 | 20, 20, 20 | 47k |
| 303 | Council: Sol (low) + Sol (low) | 20 | 20, 20 | 87k |

### What it shows

1. **A council can beat every one of its members.** In set 302 the two Sol seats' own answers scored 15 and 16; the council's final answer scored 20. They disagreed on 7 problems and the final answer got all 7 right. On two of them (Q16, Q18) **both members were wrong, with different numbers** (200 and 840; 579 and 75), and the final step, which works out every disputed item again, reached the right answer (960; 81). Voting cannot do that: it can only pick among the answers it was given.
2. **A partner must be able to do the work.** GPT-6 Luna at low thinking cannot do this mathematics without tools: alone it refused, and told to answer everything it guessed and scored 0. With such a partner the team was no better than Haiku's own answer in two sets of three; in the third (102) it gained 2, and both fixes were Haiku correcting its own off-by-one slips (885 → 886, 725 → 726) while re-checking disputed items, not anything Luna knew.
3. **Asking more than once is most of the gain, and it is cheaper.** In all three sets the majority vote of three Sol runs reached the same final score as the council (20 each time) for 47-91k tokens against the council's 87-116k. Set 303 separated nobody: every run got all 20. GPT's reading of the literature (majority voting explains most debate gains) holds here so far. The council's advantage is the case in point 1, when every independent answer is wrong; three sets are too few to say how often that happens.
4. **Models fail on the same things.** Across all runs the misses cluster in the same few problem types: counting numbers by digit sum and divisibility (missed in 5 of 7 runs checked), the 10^15th term of a recurrence, and constrained lattice paths. When every member makes the same mistake, neither voting nor a council can fix it.
5. **Run-to-run variation is large.** The same model at the same setting scored 15 to 20 on one set of problems (Sol in set 302: 18 alone, 20, 20, 19 in the vote, 15 and 16 inside the council). One run is not a measurement; compare members inside the same run, and repeat.

### The honest answer

Yes, combining raises the score, but under two conditions: every member must be able to do the task on its own, and the gain shows up where single answers are unreliable. Most of it comes from having several independent attempts; a plain majority vote gets most of it at lower cost. A council adds something a vote cannot, fixing problems that every member got wrong, and it did so in one of three sets. A weak partner does not help: it adds cost and noise.

Not yet measured, and needed before stronger claims: more sets (the differences here are a few problems), a council of two different strong models (Haiku + Sol; Claude's weekly limit stopped those runs), the same total budget for every condition, and problem families that do not overlap with what both models find hard.

## What we learned

1. **On a clear specification of this size, a top model alone gets everything right.** Both Claude Opus 5.5 and GPT-6.1 Sol passed every hidden test of both tasks. A team cannot be more accurate than 100%; it can only cost more, because the other model reads and tests the work.
2. **The reviewer found real issues anyway.** In the sheet run, Sol asked for four changes the hidden tests did not cover. Whether that matters depends on what you are building; for a product, it is the point of review.
3. **A team survives what stops a single AI.** The team run stalled because Claude ran out of usage, a limit any single-model setup also hits. Roundtable now recognises "you've hit your limit · resets 9:20pm", stops retrying until then, and hands that AI's unfinished tasks to the others, whose branch starts from its work, and its reviews to another reviewer.
4. **Planning shape matters for speed.** The quick planner made the second AI's test-writing task wait for the first AI's code, so it sat idle for the first minutes. Quick plans are now told to let independent work run in parallel.

5. **A team is as good as its best member, and much better than its weakest.** On the pond, Luna alone broke (its simulation turned into NaN; the owner, clicking the water, saw it "go dry"), Haiku alone passed everything, and the two together passed everything. That is a real gain over Luna, not over Haiku, and it cost about ten times Luna's tokens.

6. **Combining models can beat the best one, once the council is set up for it.** On the hard quiz the first council only matched Haiku: Luna's review had question 14 right, but Haiku wrote the final answer and kept its own wrong formula (one vote each). Two changes fixed that: Roundtable now lists the exact items where numbered answers disagree and has the reviewers and the final writer work each out again, and council members may check numbers with `python -c` (Codex stays in its read-only sandbox). After that the team scored 30/30 in three runs out of three, against 28-29 for Haiku alone and 17-18 for Luna alone, at about 4.5 times Haiku's tokens.

## Tokens

A team always uses more tokens than one model: both read the task, and one checks the other. Measured overheads were much larger than that, though, and two of them are now cut: a background run no longer resumes a conversation whose prompt cache has gone cold (one model had spent 666k tokens re-reading its own history), and plans are kept to about one task per builder, since every task costs a run and a review. Choosing Light checking removes reviews entirely.

## Next

The cases where a team should beat one AI are the ones where a single model makes mistakes: smaller and cheaper models, vague goals, large existing codebases, and long multi-part work. The benchmark accepts any model and effort, e.g.

```bash
rt bench run --task sql --solo claude:claude-haiku-5-5:low --solo codex:gpt-6-luna:low --team claude:claude-haiku-5-5:low,codex:gpt-6-luna:low
```
