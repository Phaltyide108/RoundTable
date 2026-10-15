"""Fresh competition-style problems for `rt bench run --task fresh`, new for every run.

Published problem sets (even AIME 2025) end up in the models' training data: a model can
recall the answers instead of working them out. These problems are made from a seed at the
start of a run, with random numbers in each, so nobody has seen them. The numbers are large
enough that counting by hand is hopeless: each needs the right idea (inclusion-exclusion,
Lucas' theorem, periodicity, a recurrence, digit-by-digit counting, Pick's theorem, ...)
carried out without a slip. Every answer is computed here by a program (dynamic programming
or brute force), so it is right. Every contender in one run gets the same problems.

Each answer is an integer from 0 to 999, as in the AIME.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache
from itertools import combinations
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


def _dice_count(parts: int, faces: int, total: int) -> int:
    """Ways for `parts` dice with faces 1..faces to add up to total."""
    ways = [1] + [0] * total
    for _ in range(parts):
        nxt = [0] * (total + 1)
        for s, w in enumerate(ways):
            if w:
                for f in range(1, faces + 1):
                    if s + f <= total:
                        nxt[s + f] += w
        ways = nxt
    return ways[total]


def _digit_sum_upto(n: int, target: int) -> int:
    """How many k in [0, n] have digit sum `target`."""
    digits = list(map(int, str(n)))

    @lru_cache(None)
    def go(i, left, tight):
        if left < 0:
            return 0
        if i == len(digits):
            return 1 if left == 0 else 0
        top = digits[i] if tight else 9
        return sum(go(i + 1, left - d, tight and d == top) for d in range(top + 1))
    return go(0, target, True)


def _phi(n: int) -> int:
    out = n
    for p in _factor(n):
        out -= out // p
    return out


def _divisors(n: int) -> list[int]:
    ds = [1]
    for p, e in _factor(n).items():
        ds = [d * p ** k for d in ds for k in range(e + 1)]
    return ds


def _tower_mod(tower: list[int], m: int) -> int:
    """tower[0]^(tower[1]^(...)) mod m, by the generalised Euler theorem (exponent reduced mod phi, kept large)."""
    if m == 1:
        return 0
    if len(tower) == 1:
        return tower[0] % m
    rest = tower[1:]
    big = 1
    for x in reversed(rest):                     # is the exponent at least 64? (then the reduction is exact)
        big = x ** big if big < 7 else 10 ** 9
        if big >= 64:
            break
    if big < 64:
        e = 1
        for x in reversed(rest):
            e = x ** e
        return pow(tower[0], e, m)
    ph = _phi(m)
    return pow(tower[0], _tower_mod(rest, ph) + ph, m)


def _ring_avoiding(n: int, pairs) -> int:
    """Seatings of 1..n around a table (rotations equal) with no forbidden pair side by side, by inclusion-exclusion:
    forcing a set of pairs together glues people into blocks; it works only if the glued pairs form paths."""
    total = 0
    for k in range(len(pairs) + 1):
        for chosen in combinations(pairs, k):
            deg: dict[int, int] = {}
            parent = {v: v for v in range(1, n + 1)}

            def find(v):
                while parent[v] != v:
                    parent[v] = parent[parent[v]]
                    v = parent[v]
                return v
            ok, cycle = True, False
            for a, b in chosen:
                deg[a], deg[b] = deg.get(a, 0) + 1, deg.get(b, 0) + 1
                ra, rb = find(a), find(b)
                if deg[a] > 2 or deg[b] > 2:
                    ok = False
                    break
                if ra == rb:
                    cycle = True                       # a closed ring: possible only if it is everyone, the last pair chosen
                    continue
                parent[ra] = rb
            if not ok:
                continue
            if cycle:
                if k == n and len(deg) == n and len({find(v) for v in deg}) == 1 and n >= 3:
                    total += (-1) ** k * 2             # the table is exactly that ring, either way round
                continue
            paths = len({find(v) for v in deg})       # blocks of two or more people, each can face either way
            blocks = n - k
            total += (-1) ** k * math.factorial(blocks - 1) * 2 ** paths
    return total


# ---------------------------------------------------------------- the families: each returns (question, answer)

def inclusion_exclusion(r: random.Random):
    a, b, c = r.sample([6, 10, 14, 15, 21, 22, 26, 33, 35], 3)
    d = r.choice([4, 9, 25, 49])
    n = r.randint(10 ** 6, 10 ** 7)
    total = 0
    for mask in range(1, 8):
        chosen = [x for i, x in enumerate((a, b, c)) if mask >> i & 1]
        l1 = math.lcm(*chosen)
        sign = 1 if len(chosen) % 2 else -1
        total += sign * (n // l1 - n // math.lcm(l1, d))
    return f"How many integers k with 1 ≤ k ≤ {n} are divisible by at least one of {a}, {b}, {c}, but not by {d}? Give the answer modulo 1000.", total % 1000


def lattice_paths(r: random.Random):
    m, n = r.randint(16, 20), r.randint(14, 18)
    blocked = set()
    while len(blocked) < 5:
        blocked.add((r.randint(1, m - 1), r.randint(1, n - 1)))
    grid = [[0] * (n + 1) for _ in range(m + 1)]
    for x in range(m + 1):
        for y in range(n + 1):
            if (x, y) in blocked:
                continue
            grid[x][y] = 1 if x == y == 0 else (grid[x - 1][y] if x else 0) + (grid[x][y - 1] if y else 0)
    pts = ", ".join(map(str, sorted(blocked)))
    return (f"A path goes from (0, 0) to ({m}, {n}) using unit steps right and up. It may not pass through any of the points {pts}. "
            f"How many such paths are there? Give the answer modulo 1000."), grid[m][n] % 1000


def power_tower(r: random.Random):
    m = r.choice([x for x in range(300, 1000) if len(_factor(x)) >= 2])
    a, b, c, d = r.randint(3, 40), r.randint(3, 12), r.randint(3, 9), r.randint(5, 30)
    return (f"What is the remainder when {a}^({b}^({c}^{d})) is divided by {m}? (A tower of powers: {c}^{d} is the exponent of {b}, "
            f"and that whole number is the exponent of {a}.)"), _tower_mod([a, b, c, d], m)


def four_part_partitions(r: random.Random):
    s = r.randint(150, 400)
    # partitions into exactly 4 parts = partitions of s - 4 into parts of size at most 4
    ways = [1] + [0] * (s - 4)
    for part in range(1, 5):
        for v in range(part, s - 3):
            ways[v] += ways[v - part]
    return f"In how many ways can {s} be written as a + b + c + d with positive integers a ≤ b ≤ c ≤ d? Give the answer modulo 1000.", ways[s - 4] % 1000


def trailing_zeros_base(r: random.Random):
    base = r.choice([72, 96, 108, 144, 200, 360, 392, 500, 675])
    n = r.randint(10 ** 4, 10 ** 5)
    ans = min(sum(n // p ** k for k in range(1, 40)) // e for p, e in _factor(base).items())
    return f"Written in base {base}, the number {n}! ends in how many zeros? Give the answer modulo 1000.", ans % 1000


def dice_sum(r: random.Random):
    k, s = r.choice([(7, 8), (8, 6), (6, 10), (9, 6), (7, 10)])
    mid = k * (s + 1) // 2
    t = r.randint(mid - 8, mid + 8)
    return f"{k} distinguishable dice, each with faces 1 to {s}, are rolled. In how many of the {s}^{k} outcomes is the total exactly {t}? Give the answer modulo 1000.", _dice_count(k, s, t) % 1000


def necklaces(r: random.Random):
    n, c = r.randint(12, 40), r.randint(2, 5)
    total = sum(_phi(d) * c ** (n // d) for d in range(1, n + 1) if n % d == 0) // n
    return (f"A necklace has {n} beads in a circle, each one of {c} colours. Two necklaces are the same if one can be rotated into the other "
            f"(not flipped). How many different necklaces are there? Give the answer modulo 1000."), total % 1000


def digit_sum_count(r: random.Random):
    n = r.randint(10 ** 8, 10 ** 9)
    t = r.randint(25, 45)
    m = r.choice([7, 11, 13])
    digits = list(map(int, str(n)))

    @lru_cache(None)
    def go(i, left, rem, tight):
        if left < 0:
            return 0
        if i == len(digits):
            return 1 if left == 0 and rem == 0 else 0
        top = digits[i] if tight else 9
        return sum(go(i + 1, left - d, (rem * 10 + d) % m, tight and d == top) for d in range(top + 1))
    return (f"How many integers k with 1 ≤ k ≤ {n} have digits adding up to exactly {t} and are divisible by {m}? "
            f"Give the answer modulo 1000."), go(0, t, 0, True) % 1000


def subset_sums(r: random.Random):
    n, size, m = r.randint(25, 40), r.randint(5, 10), r.choice([7, 9, 11, 13])
    ways = [[0] * m for _ in range(size + 1)]          # ways[k][s]: subsets of k elements with sum ≡ s
    ways[0][0] = 1
    for v in range(1, n + 1):
        for k in range(size, 0, -1):
            ways[k] = [ways[k][i] + ways[k - 1][(i - v) % m] for i in range(m)]
    return f"How many {size}-element subsets of {{1, 2, ..., {n}}} have a sum divisible by {m}? Give the answer modulo 1000.", ways[size][0] % 1000


def pick_triangle(r: random.Random):
    while True:
        pts = [(r.randint(0, 400), r.randint(0, 400)) for _ in range(3)]
        (x1, y1), (x2, y2), (x3, y3) = pts
        area2 = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1))
        if area2 < 20000:
            continue
        b = sum(math.gcd(abs(p[0] - q[0]), abs(p[1] - q[1])) for p, q in ((pts[0], pts[1]), (pts[1], pts[2]), (pts[2], pts[0])))
        inside = (area2 - b + 2) // 2
        return (f"How many points with integer coordinates lie strictly inside the triangle with vertices {pts[0]}, {pts[1]} and {pts[2]}? "
                f"Give the answer modulo 1000."), inside % 1000


def bounded_sums(r: random.Random):
    k, cap = r.randint(5, 8), r.randint(6, 15)
    s_ = r.randint(cap * k // 3, cap * k * 2 // 3)
    ways = [1] + [0] * s_
    for _ in range(k):
        ways = [sum(ways[v - x] for x in range(0, min(cap, v) + 1)) for v in range(s_ + 1)]
    return (f"How many ordered {k}-tuples (x1, ..., x{k}) of integers with 0 ≤ xi ≤ {cap} for every i have x1 + ... + x{k} = {s_}? "
            f"Give the answer modulo 1000."), ways[s_] % 1000


def lucas(r: random.Random):
    ans = 0
    while ans == 0:                   # 0 is the usual answer; a lazy guess of 0 should not score
        p = r.choice([7, 11, 13, 17, 19, 23, 29, 31])
        n = r.randint(10 ** 6, 10 ** 7)
        k = r.randint(10 ** 5, n - 10 ** 5)
        ans, nn, kk = 1, n, k
        while nn or kk:
            ans = ans * math.comb(nn % p, kk % p) % p
            nn, kk = nn // p, kk // p
    return f"What is the remainder when the binomial coefficient C({n}, {k}) is divided by {p}?", ans


def coprime_count(r: random.Random):
    m = r.choice([2310, 3570, 4290, 6006, 7410, 10010, 15015, 30030])
    n = r.randint(10 ** 6, 10 ** 7)
    primes = list(_factor(m))
    total = 0
    for mask in range(1 << len(primes)):
        prod = math.prod(p for i, p in enumerate(primes) if mask >> i & 1)
        total += (-1) ** bin(mask).count("1") * (n // prod)
    return f"How many integers k with 1 ≤ k ≤ {n} share no common factor greater than 1 with {m}? Give the answer modulo 1000.", total % 1000


def domino_tilings(r: random.Random):
    n = r.choice(range(40, 122, 2))
    a = [1, 0, 3, 0]
    while len(a) <= n:
        a.append(4 * a[-2] - a[-4])
    return f"In how many ways can a 3 × {n} rectangle be tiled with 1 × 2 dominoes? Give the answer modulo 1000.", a[n] % 1000


def fixed_points(r: random.Random):
    n = r.randint(15, 26)
    k = r.randint(2, 5)
    d = [1, 0]
    for i in range(2, n + 1):
        d.append((i - 1) * (d[-1] + d[-2]))
    return f"How many permutations of {{1, 2, ..., {n}}} have exactly {k} fixed points? Give the answer modulo 1000.", math.comb(n, k) * d[n - k] % 1000


def gcd_sum(r: random.Random):
    while True:
        n = r.randint(10 ** 5, 10 ** 6)
        if len(_factor(n)) >= 3:
            break
    total = sum(d * _phi(n // d) for d in _divisors(n))
    return f"Find gcd(1, {n}) + gcd(2, {n}) + ... + gcd({n}, {n}). Give the answer modulo 1000.", total % 1000


def quadratic_congruence(r: random.Random):
    m = r.choice([120, 168, 240, 252, 360, 420, 504, 840])
    while True:
        c = r.randint(1, m - 1)
        roots = [x for x in range(m) if (x * x + c) % m == 0]
        if roots:
            break
    n = r.randint(10 ** 5, 10 ** 6)
    ans = 0
    for x in roots:
        lo = x if x >= 1 else m                       # the k ≡ x (mod m) with 1 ≤ k ≤ n
        if lo <= n:
            cnt = (n - lo) // m + 1
            ans += cnt * lo + m * cnt * (cnt - 1) // 2
    return f"Find the sum of all integers k with 1 ≤ k ≤ {n} such that k² + {c} is divisible by {m}. Give the answer modulo 1000.", ans % 1000


def nondecreasing_digits(r: random.Random):
    d = r.randint(9, 14)
    m = r.choice([7, 11, 13])

    @lru_cache(None)
    def go(left, last, rem):
        if left == 0:
            return 1 if rem == 0 else 0
        return sum(go(left - 1, x, (rem * 10 + x) % m) for x in range(last, 10))
    return f"How many {d}-digit positive integers have no zero digit, digits that never decrease from left to right, and are divisible by {m}? Give the answer modulo 1000.", go(d, 1, 0) % 1000


def seating(r: random.Random):
    n = 12
    pairs = r.sample(list(combinations(range(1, n + 1), 2)), 5)
    text = ", ".join(f"{a} and {b}" for a, b in pairs)
    return (f"{n} people, numbered 1 to {n}, sit around a round table; seatings that are rotations of each other count as the same, but reflections count as different. "
            f"None of these pairs may sit next to each other: {text}. How many seatings are possible? Give the answer modulo 1000."), _ring_avoiding(n, pairs) % 1000


def recurrence_far(r: random.Random):
    a1, a2, a3 = r.randint(1, 9), r.randint(1, 9), r.randint(1, 9)
    p, q, w = r.randint(1, 5), r.randint(1, 5), r.randint(1, 5)
    k = r.randint(10 ** 14, 10 ** 15)

    def mul(x, y):
        return [[sum(x[i][t] * y[t][j] for t in range(3)) % 1000 for j in range(3)] for i in range(3)]
    res, base, e = [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [[p, q, w], [1, 0, 0], [0, 1, 0]], k - 3
    while e:
        if e & 1:
            res = mul(res, base)
        base = mul(base, base)
        e >>= 1
    ans = (res[0][0] * a3 + res[0][1] * a2 + res[0][2] * a1) % 1000
    return (f"A sequence has a(1) = {a1}, a(2) = {a2}, a(3) = {a3} and a(n) = {p}·a(n−1) + {q}·a(n−2) + {w}·a(n−3) for n ≥ 4. "
            f"What are the last three digits of a({k}), as a number from 0 to 999?"), ans


FAMILIES: list[Callable[[random.Random], tuple[str, int]]] = [
    inclusion_exclusion, lattice_paths, power_tower, four_part_partitions, trailing_zeros_base, dice_sum, necklaces,
    digit_sum_count, subset_sums, pick_triangle, bounded_sums, lucas, coprime_count, domino_tilings,
    fixed_points, gcd_sum, quadratic_congruence, nondecreasing_digits, seating, recurrence_far,
]


def generate(seed: int) -> list[dict]:
    """The same seed gives the same problems; their order is shuffled too."""
    r = random.Random(seed)
    out = []
    for fam in FAMILIES:
        q, a = fam(r)
        assert 0 <= a <= 999, (fam.__name__, a)
        out.append({"q": q, "a": [str(a)], "family": fam.__name__})
    r.shuffle(out)
    return out
