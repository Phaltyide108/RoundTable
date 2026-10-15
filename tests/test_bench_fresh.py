"""The fresh benchmark: problems made from a seed, answers checked here a second, independent way."""

import math
import random
import re

from roundtable_ai import bench, bench_fresh


def test_same_seed_same_problems_and_every_answer_fits():
    a, b = bench_fresh.generate(5), bench_fresh.generate(5)
    assert a == b and bench_fresh.generate(6) != a
    assert len(a) == len(bench_fresh.FAMILIES) == 20
    for seed in range(8):
        for q in bench_fresh.generate(seed):
            assert 0 <= int(q["a"][0]) <= 999 and q["q"].strip()


def _nums(text):
    return [int(x) for x in re.findall(r"\d+", text)]


def test_answers_agree_with_a_second_method():
    for seed in range(6):
        r = random.Random(seed)
        q, a = bench_fresh.three_part_partitions(r)
        s = _nums(q)[0]
        assert a == round(s * s / 12)                         # the closed form for partitions into 3 parts
        q, a = bench_fresh.egyptian_pairs(r)
        n = _nums(q)[-1]
        assert a == sum(1 for x in range(n + 1, n + n * n + 1) if (n * x) % (x - n) == 0)
        q, a = bench_fresh.pick_triangle(r)
        xs = _nums(q)
        pts = [(xs[i], xs[i + 1]) for i in (0, 2, 4)]

        def inside(px, py):
            def side(p, q2):
                return (q2[0] - p[0]) * (py - p[1]) - (q2[1] - p[1]) * (px - p[0])
            d = [side(pts[0], pts[1]), side(pts[1], pts[2]), side(pts[2], pts[0])]
            return all(v > 0 for v in d) or all(v < 0 for v in d)
        assert a == sum(1 for x in range(46) for y in range(46) if inside(x, y))
        q, a = bench_fresh.power_mod(r)
        base, e, m = _nums(q)
        assert a == pow(base, e, m)
        q, a = bench_fresh.fixed_points(r)
        n, k = _nums(q)[2], _nums(q)[3]
        assert a == math.comb(n, k) * round(math.factorial(n - k) / math.e) % 1000   # derangements: round(m!/e)
    known = {10: 571, 12: 2131, 14: 7953, 16: 29681, 18: 110771, 20: 413403}   # 3 x n domino tilings (OEIS A001835)
    for seed in range(12):
        q, a = bench_fresh.domino_tilings(random.Random(seed))
        assert a == known[_nums(q)[1]] % 1000


def test_fresh_task_runs_with_a_seed_and_reports_it(tmp_path):
    assert bench.meta("fresh")["generated"] == "fresh" and bench.meta("fresh")["offline"]
    bench.set_seed("fresh", 77)
    qs = bench.quiz_questions("fresh")
    assert bench.count_hidden("fresh") == 20
    perfect = "my working\nFINAL ANSWERS\n" + "\n".join(f"{i}: {q['a'][0]}" for i, q in enumerate(qs, 1))
    assert bench.score_quiz("fresh", perfect)["passed"] == 20
    assert "Problem 20." in bench.quiz_prompt("fresh") and len(bench.quiz_prompt("fresh")) < 16000
    report = {"task": "fresh", "minutes_limit": 5, "mode": "quick", "review": "mid", "at": "now", "seed": 77, "results": []}
    assert "problems from seed 77" in bench.markdown(report)
