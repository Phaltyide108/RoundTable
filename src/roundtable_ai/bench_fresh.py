"""Fresh competition-style problems for `rt bench run --task fresh`, new for every run.

Published problem sets (even AIME 2025) end up in the models' training data: a model can
recall the answers instead of working them out. These problems are made from a seed at the
start of a run, with random numbers in each, so nobody has seen them; every answer is worked
out here by brute force, so it is right. Every contender in one run gets the same problems.

Each answer is an integer from 0 to 999, as in the AIME.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache
from itertools import combinations, permutations, product
from typing import Callable


def _factor(n: int) -> dict[int, int]:
    out: dict[int, int] = {}
    p = 2
    while p * p <= n:
        while n % p == 0:
            out[p] = out.get(p, 0) + 1
            n //= p
        p += 1
    if n > 1:
        out[n] = out.get(n, 0) + 1
    return out


def _ndiv(n: int) -> int:
    return math.prod(e + 1 for e in _factor(n).values())


# ---------------------------------------------------------------- the families: each returns (question, answer)

def divisible_but_not(r: random.Random):
    a, b = r.sample([3, 4, 6, 7, 9, 10, 11, 14, 15], 2)
    c = r.choice([x for x in (5, 8, 12, 13, 21, 22, 25) if x not in (a, b)])
    n = r.randint(2000, 9000)
    ans = sum(1 for k in range(1, n + 1) if (k % a == 0 or k % b == 0) and k % c)
    return f"How many integers k with 1 ≤ k ≤ {n} are divisible by {a} or by {b}, but not by {c}? Give the answer modulo 1000.", ans % 1000


def lattice_paths(r: random.Random):
    m, n = r.randint(7, 10), r.randint(6, 9)
    blocked = set()
    while len(blocked) < 2:
        p = (r.randint(1, m - 1), r.randint(1, n - 1))
        blocked.add(p)
    b1, b2 = sorted(blocked)

    @lru_cache(None)
    def ways(x, y):
        if (x, y) in blocked or x < 0 or y < 0:
            return 0
        if x == 0 and y == 0:
            return 1
        return ways(x - 1, y) + ways(x, y - 1)
    ans = ways(m, n)
    return (f"A path goes from (0, 0) to ({m}, {n}) using unit steps right (+1, 0) and up (0, +1). It may not pass through the points "
            f"{b1} or {b2}. How many such paths are there? Give the answer modulo 1000."), ans % 1000


def power_mod(r: random.Random):
    a = r.randint(3, 97)
    m = r.choice([x for x in range(150, 1000) if len(_factor(x)) >= 2 and math.gcd(a, x) == 1])
    e = r.randint(10 ** 6, 10 ** 9)
    return f"What is the remainder when {a}^{e} is divided by {m}?", pow(a, e, m)


def three_part_partitions(r: random.Random):
    s = r.randint(45, 105)
    ans = sum(1 for x in range(1, s) for y in range(x, s) if s - x - y >= y)
    return f"In how many ways can {s} be written as a sum a + b + c of positive integers with a ≤ b ≤ c?", ans


def trailing_zeros_base(r: random.Random):
    base = r.choice([12, 18, 20, 24, 28, 36, 45, 50, 72])
    n = r.randint(150, 900)
    f = _factor(base)
    ans = min(sum(n // p ** k for k in range(1, 20)) // e for p, e in f.items())
    return f"Written in base {base}, the number {n}! ends in how many zeros?", ans


def dice_sum(r: random.Random):
    k, s = r.choice([(4, 6), (4, 8), (5, 6), (4, 10), (5, 8)])
    mid = k * (s + 1) // 2
    t = r.randint(mid - 5, mid + 5)
    ans = sum(1 for roll in product(range(1, s + 1), repeat=k) if sum(roll) == t)
    return f"{k} distinguishable dice, each with faces 1 to {s}, are rolled. In how many of the {s}^{k} outcomes is the total exactly {t}? Give the answer modulo 1000.", ans % 1000


def divisors_of_expression(r: random.Random):
    while True:
        a, b = r.sample([12, 18, 20, 28, 30, 45, 50, 63, 72, 75, 84, 98], 2)
        i, j = r.randint(2, 5), r.randint(1, 4)
        n = a ** i * b ** j
        ans = _ndiv(n)
        if ans < 1000:
            return f"How many positive divisors does {a}^{i} · {b}^{j} have?", ans


def digit_sum_count(r: random.Random):
    n = r.randint(20000, 99999)
    t = r.randint(14, 30)
    ans = sum(1 for k in range(1, n + 1) if sum(map(int, str(k))) == t)
    return f"How many integers k with 1 ≤ k ≤ {n} have digits adding up to exactly {t}? Give the answer modulo 1000.", ans % 1000


def subset_sums(r: random.Random):
    n = r.randint(11, 15)
    m = r.choice([3, 5, 6, 7, 9])
    ans = sum(1 for mask in range(1 << n) if sum(i + 1 for i in range(n) if mask >> i & 1) % m == 0)
    return f"How many subsets of {{1, 2, ..., {n}}} (the empty set included) have a sum divisible by {m}? Give the answer modulo 1000.", ans % 1000


def pick_triangle(r: random.Random):
    while True:
        pts = [(r.randint(0, 45), r.randint(0, 45)) for _ in range(3)]
        (x1, y1), (x2, y2), (x3, y3) = pts
        area2 = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))
        if area2 == 0:
            continue
        b = sum(math.gcd(abs(p[0] - q[0]), abs(p[1] - q[1])) for p, q in ((pts[0], pts[1]), (pts[1], pts[2]), (pts[2], pts[0])))
        inside = (area2 - b + 2) // 2
        if 100 <= inside < 1000:
            return f"How many points with integer coordinates lie strictly inside the triangle with vertices {pts[0]}, {pts[1]} and {pts[2]}?", inside


def egyptian_pairs(r: random.Random):
    while True:
        n = 2 ** r.randint(1, 5) * 3 ** r.randint(0, 3) * r.choice([1, 5, 7, 5 * 7, 11])
        ans = _ndiv(n * n)
        if 30 < ans < 1000:
            return f"How many ordered pairs (x, y) of positive integers satisfy 1/x + 1/y = 1/{n}?", ans


def binomial_mod_prime(r: random.Random):
    p = r.choice([101, 103, 107, 109, 113, 127])
    n = r.randint(3000, 12000)
    k = r.randint(200, n - 200)
    return f"What is the remainder when the binomial coefficient C({n}, {k}) is divided by the prime {p}?", math.comb(n, k) % p


def coprime_count(r: random.Random):
    m = r.choice([210, 330, 390, 462, 510, 546, 714, 770, 858, 1155])
    n = r.randint(3000, 9999)
    ans = sum(1 for k in range(1, n + 1) if math.gcd(k, m) == 1)
    return f"How many integers k with 1 ≤ k ≤ {n} share no common factor greater than 1 with {m}? Give the answer modulo 1000.", ans % 1000


def domino_tilings(r: random.Random):
    n = r.choice([10, 12, 14, 16, 18, 20])
    a = [1, 0, 3, 0]
    while len(a) <= n:
        a.append(4 * a[-2] - a[-4])
    return f"In how many ways can a 3 × {n} rectangle be tiled with 1 × 2 dominoes (each placed horizontally or vertically)? Give the answer modulo 1000.", a[n] % 1000


def fixed_points(r: random.Random):
    n = r.randint(8, 12)
    k = r.randint(1, 3)
    d = [1, 0]
    for i in range(2, n + 1):
        d.append((i - 1) * (d[-1] + d[-2]))
    ans = math.comb(n, k) * d[n - k]
    return f"How many permutations of {{1, 2, ..., {n}}} have exactly {k} fixed point{'s' if k > 1 else ''}? Give the answer modulo 1000.", ans % 1000


def lcm_pairs(r: random.Random):
    while True:
        L = r.choice([2, 4, 8, 16]) * r.choice([3, 9, 27]) * r.choice([5, 25, 7, 49, 1]) * r.choice([1, 11, 13])
        ds = [d for d in range(1, L + 1) if L % d == 0]
        ans = sum(1 for a in ds for b in ds if a * b // math.gcd(a, b) == L)
        if 40 < ans < 1000:
            return f"How many ordered pairs (a, b) of positive integers have least common multiple exactly {L}?", ans


def quadratic_residue_sum(r: random.Random):
    m = r.choice([24, 40, 48, 56, 60, 72, 84, 90, 120])
    c = r.randint(1, m - 1)
    n = r.randint(500, 3000)
    while not any((k * k + c) % m == 0 for k in range(m)):
        c = r.randint(1, m - 1)
    ans = sum(k for k in range(1, n + 1) if (k * k + c) % m == 0)
    return f"Find the sum of all integers k with 1 ≤ k ≤ {n} such that k² + {c} is divisible by {m}. Give the answer modulo 1000.", ans % 1000


def nondecreasing_digits(r: random.Random):
    d = r.randint(4, 6)
    m = r.choice([3, 4, 7, 11])
    ans = sum(1 for digits in product(range(1, 10), repeat=d) if list(digits) == sorted(digits) and int("".join(map(str, digits))) % m == 0)
    return f"How many {d}-digit positive integers have no zero digit, digits that never decrease from left to right, and are divisible by {m}?", ans % 1000


def seating(r: random.Random):
    n = r.randint(7, 9)
    pairs = r.sample(list(combinations(range(1, n + 1), 2)), 2)
    ans = 0
    for p in permutations(range(2, n + 1)):
        ring = (1,) + p
        pos = {v: i for i, v in enumerate(ring)}
        if all((pos[a] - pos[b]) % n not in (1, n - 1) for a, b in pairs):
            ans += 1
    (a1, b1), (a2, b2) = pairs
    return (f"{n} people, numbered 1 to {n}, sit around a round table; seatings that are rotations of each other count as the same. "
            f"Person {a1} refuses to sit next to person {b1}, and person {a2} refuses to sit next to person {b2}. "
            f"How many seatings are possible? Give the answer modulo 1000."), ans % 1000


def recurrence(r: random.Random):
    a1, a2 = r.randint(1, 9), r.randint(1, 9)
    p, q = r.randint(2, 5), r.randint(1, 4)
    k = r.randint(40, 90)
    seq = [a1, a2]
    while len(seq) < k:
        seq.append(p * seq[-1] + q * seq[-2])
    return f"A sequence has a(1) = {a1}, a(2) = {a2} and a(n) = {p}·a(n−1) + {q}·a(n−2) for n ≥ 3. What are the last three digits of a({k}) (as a number from 0 to 999)?", seq[k - 1] % 1000


FAMILIES: list[Callable[[random.Random], tuple[str, int]]] = [
    divisible_but_not, lattice_paths, power_mod, three_part_partitions, trailing_zeros_base, dice_sum, divisors_of_expression,
    digit_sum_count, subset_sums, pick_triangle, egyptian_pairs, binomial_mod_prime, coprime_count, domino_tilings,
    fixed_points, lcm_pairs, quadratic_residue_sum, nondecreasing_digits, seating, recurrence,
]


def generate(seed: int) -> list[dict[str, str]]:
    """The same seed gives the same problems; their order is shuffled too."""
    r = random.Random(seed)
    out = []
    for fam in FAMILIES:
        q, a = fam(r)
        assert 0 <= a <= 999, (fam.__name__, a)
        out.append({"q": q, "a": [str(a)], "family": fam.__name__})
    r.shuffle(out)
    return out
