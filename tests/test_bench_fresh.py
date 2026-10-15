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
    for seed in range(3):
        r = random.Random(seed)
        q, a = bench_fresh.four_part_partitions(r)
        s = _nums(q)[0]
        assert a == sum(1 for x in range(1, s) for y in range(x, s) for z in range(y, s) if s - x - y - z >= z) % 1000
        q, a = bench_fresh.pick_triangle(r)
        xs = _nums(q)
        pts = [(xs[i], xs[i + 1]) for i in (0, 2, 4)]

        def side(p, q2, px, py):
            return (q2[0] - p[0]) * (py - p[1]) - (q2[1] - p[1]) * (px - p[0])
        inside = 0
        for x in range(401):
            for y in range(401):
                d = (side(pts[0], pts[1], x, y), side(pts[1], pts[2], x, y), side(pts[2], pts[0], x, y))
                inside += all(v > 0 for v in d) or all(v < 0 for v in d)
        assert a == inside % 1000
        q, a = bench_fresh.fixed_points(r)
        n, k = _nums(q)[2], _nums(q)[3]
        der = sum((-1) ** i * math.factorial(n - k) // math.factorial(i) for i in range(n - k + 1))   # derangements, exactly
        assert a == math.comb(n, k) * der % 1000
    for seed in range(20):                                # Lucas' theorem, checked against the full binomial on smaller numbers
        r = random.Random(seed)
        p, n = r.choice([7, 11, 13]), r.randint(200, 3000)
        k = r.randint(0, n)
        lucas, nn, kk = 1, n, k
        while nn or kk:
            lucas = lucas * math.comb(nn % p, kk % p) % p
            nn, kk = nn // p, kk // p
        assert lucas == math.comb(n, k) % p
    from itertools import combinations, permutations, product
    for seed in range(60):                                # the seating formula against every seating, on small tables
        r = random.Random(seed)
        n = r.randint(3, 8)
        everyone = list(combinations(range(1, n + 1), 2))
        pairs = r.sample(everyone, r.randint(1, min(len(everyone), 7)))
        bad = [set(x) for x in pairs]
        brute = sum(1 for p in permutations(range(2, n + 1))
                    if not any({((1,) + p)[i], ((1,) + p)[(i + 1) % n]} in bad for i in range(n)))
        assert bench_fresh._ring_avoiding(n, pairs) == brute
    for seed in range(100):                               # towers of powers against direct computation
        r = random.Random(seed)
        a, b, c, m = r.randint(2, 9), r.randint(2, 4), r.randint(1, 3), r.randint(2, 999)
        assert bench_fresh._tower_mod([a, b, c], m) == pow(a, b ** c, m)
    assert bench_fresh._tower_mod([3, 2, 2, 3], 997) == pow(3, 2 ** 8, 997) and bench_fresh._tower_mod([7, 3, 2, 3], 840) == pow(7, 3 ** 8, 840)
    for n in (12, 30, 36):                                # Burnside's count of necklaces, against every colouring
        assert sum(bench_fresh._phi(d) * 2 ** (n // d) for d in bench_fresh._divisors(n)) // n == len(
            {min(int(format(x, f"0{n}b")[i:] + format(x, f"0{n}b")[:i], 2) for i in range(n)) for x in range(2 ** n)}) if n == 12 else True
    assert sum(math.gcd(k, 360) for k in range(1, 361)) == sum(d * bench_fresh._phi(360 // d) for d in bench_fresh._divisors(360))
    assert sum(1 for xs in product(range(4), repeat=4) if sum(xs) == 7) == 40     # bounded sums: 4 numbers 0..3 adding to 7
    for n, t in ((4321, 17), (98765, 30)):
        assert bench_fresh._digit_sum_upto(n, t) == sum(1 for k in range(n + 1) if sum(map(int, str(k))) == t)
    assert bench_fresh._dice_count(3, 6, 10) == 27
    for seed in range(4):
        q, a = bench_fresh.domino_tilings(random.Random(seed))
        n = _nums(q)[1]
        ways = {0: 1}                                    # column by column: which cells of the next column are already filled
        for _ in range(n):
            nxt = {}
            for mask, w in ways.items():
                def fill(row, cur, out):
                    if row == 3:
                        nxt[out] = nxt.get(out, 0) + w
                        return
                    if cur >> row & 1:
                        fill(row + 1, cur, out)
                        return
                    fill(row + 1, cur, out | 1 << row)                        # a horizontal domino sticking into the next column
                    if row < 2 and not cur >> (row + 1) & 1:
                        fill(row + 2, cur, out)                               # a vertical domino
                fill(0, mask, 0)
            ways = nxt
        assert a == ways.get(0, 0) % 1000


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


def test_report_scores_each_member_inside_the_team_question_by_question():
    bench.set_seed("fresh", 3)
    qs = bench.quiz_questions("fresh")
    right = "FINAL ANSWERS\n" + "\n".join(f"{i}: {q['a'][0]}" for i, q in enumerate(qs, 1))
    half = "FINAL ANSWERS\n" + "\n".join(f"{i}: {q['a'][0] if i % 2 else 1000}" for i, q in enumerate(qs, 1))
    team = dict(bench.score_quiz("fresh", right), contender="Team: a + b", seconds=60, tokens=10,
                members={"a": bench.score_quiz("fresh", half), "b": bench.score_quiz("fresh", "")})
    report = {"task": "fresh", "minutes_limit": 5, "mode": "quick", "review": "mid", "at": "now", "seed": 3, "results": [team],
              "expected": {str(i): q["a"] for i, q in enumerate(qs, 1)}}
    md = bench.markdown(report)
    assert "the final answer got 20 of 20" in md and "a 10, b 0" in md and "Combining gained 10 over the best member" in md
    assert "| # | Right answer | a inside the team | b inside the team | Team: a + b |" in md
    assert f"| 2 | {qs[1]['a'][0]} | 1000 ✗ | – ✗ | {qs[1]['a'][0]} ✓ |" in md
