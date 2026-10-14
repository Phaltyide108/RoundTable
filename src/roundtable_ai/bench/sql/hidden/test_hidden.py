"""Hidden tests for the `sql` benchmark task (standard library unittest only).

Real SQLite (the sqlite3 module) is the referee: every query runs on a fresh copy of
the same tables in SQLite and in the contender's engine, and the answers must match,
including int versus real. Each test checks one rule of TASK.md."""

import math
import sqlite3
import time
import unittest

from minisql import Database, SQLError

FIXTURE = [
    "CREATE TABLE emp (id INTEGER, name TEXT, dept TEXT, salary REAL, boss INTEGER)",
    "INSERT INTO emp VALUES (1, 'Ann', 'eng', 120000, NULL), (2, 'Bob', 'eng', 95000, 1), (3, 'Cid', 'ops', 70000, 1), "
    "(4, 'Dee', 'ops', NULL, 3), (5, 'Eve', NULL, 50000, 3), (6, 'fay', 'eng', 95000.5, 2)",
    "CREATE TABLE dept (code TEXT, title TEXT, floor INTEGER)",
    "INSERT INTO dept VALUES ('eng', 'Engineering', 3), ('ops', 'Operations', 1), ('hr', 'People', NULL)",
    "CREATE TABLE nums (a INTEGER, b REAL, c TEXT, d)",
    "INSERT INTO nums VALUES (7, 2.5, 'x', 1), (-7, -0.5, 'Y', 'q'), (NULL, NULL, NULL, NULL), (3, 3.0, '10', 2.0), (0, 0.0, '', '3')",
]


def norm_value(v):
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("bool!", v)
    if isinstance(v, int):
        return ("int", v)
    if isinstance(v, float):
        return ("real", "nan" if math.isnan(v) else round(v, 9))
    return (type(v).__name__, v)


def norm(rows, ordered):
    out = [tuple(norm_value(v) for v in (r if isinstance(r, (tuple, list)) else (r,))) for r in rows]
    return out if ordered else sorted(out, key=repr)


class Base(unittest.TestCase):
    maxDiff = 4000

    def pair(self, *setup):
        mine, ref = Database(), sqlite3.connect(":memory:")
        for st in FIXTURE + list(setup):
            mine.execute(st)
            ref.execute(st)
        return mine, ref

    def check(self, query, *setup, ordered=None):
        mine, ref = self.pair(*setup)
        want = ref.execute(query).fetchall()
        got = mine.execute(query)
        self.assertIsInstance(got, list)
        if ordered is None:
            ordered = "order by" in query.lower()
        self.assertEqual(norm(got, ordered), norm(want, ordered), query)

    def after(self, statements, query):
        """Run modifying statements on both, then compare a query."""
        mine, ref = self.pair()
        for st in statements:
            self.assertEqual(mine.execute(st), [], st)
            ref.execute(st)
        self.assertEqual(norm(mine.execute(query), "order by" in query.lower()),
                         norm(ref.execute(query).fetchall(), "order by" in query.lower()), query)

    def fails(self, *queries):
        mine, _ref = self.pair()
        for q in queries:
            with self.assertRaises(SQLError, msg=q):
                mine.execute(q)


class Basics(Base):
    def test_select_star(self): self.check("SELECT * FROM dept")
    def test_columns_and_where(self): self.check("SELECT name, salary FROM emp WHERE dept = 'eng'")
    def test_no_from(self): self.check("SELECT 1 + 1, 'a' || 'b', NULL")
    def test_aliases(self): self.check("SELECT name AS who, salary / 1000 AS k FROM emp WHERE id <= 2 ORDER BY who")
    def test_bare_alias(self): self.check("SELECT name who FROM emp WHERE id = 3")
    def test_case_insensitive_names(self): self.check("select NAME, Salary from EMP where ID = 3")
    def test_trailing_semicolon(self): self.check("SELECT id FROM emp WHERE id = 1;")
    def test_table_alias_star(self): self.check("SELECT e.* FROM emp e WHERE e.id = 2")
    def test_table_alias_as(self): self.check("SELECT x.title FROM dept AS x WHERE x.floor = 3")
    def test_string_escape(self): self.check("SELECT 'it''s', ''")
    def test_returns_empty_list(self):
        mine, _ = self.pair()
        self.assertEqual(mine.execute("SELECT id FROM emp WHERE id > 99"), [])
        self.assertEqual(mine.execute("CREATE TABLE z (q)"), [])


class Arithmetic(Base):
    def test_integer_division(self): self.check("SELECT -7 / 2, 7 / 2, 7.0 / 2, 7 / 2.0, 5 / 2")
    def test_modulo(self): self.check("SELECT -7 % 3, 7 % -3, 10 % 3")
    def test_modulo_with_real(self): self.check("SELECT 10 % 3.5, 7.9 % 2")
    def test_division_by_zero(self): self.check("SELECT 1 / 0, 1 % 0, 1.5 / 0")
    def test_null_arithmetic(self): self.check("SELECT a + NULL, NULL * 2, -b FROM nums WHERE a = 7")
    def test_text_arithmetic(self): self.check("SELECT '12abc' + 0, 'abc' + 1, '3' * '4', '2.5' + 1")
    def test_real_literals(self): self.check("SELECT 1e3, .5, 2.50, 1e3 + 1")
    def test_concat_precedence(self): self.check("SELECT 2 || 3 * 4, 1 + 2 * 3, -2 * 3, (1 + 2) * 3")
    def test_concat_numbers(self): self.check("SELECT 2.0 || '', 3 || 'x', 'a' || NULL, name || '-' || id FROM emp WHERE id = 1")
    def test_unary(self): self.check("SELECT - -3, -'3', +5, -a FROM nums WHERE a = -7")
    def test_column_arithmetic(self): self.check("SELECT id * 2 + 1, salary / 2, boss - id FROM emp ORDER BY id")


class Logic(Base):
    def test_compare_null(self): self.check("SELECT 1 = NULL, NULL = NULL, NULL <> 1, NULL < 1")
    def test_compare_mixed(self): self.check("SELECT 1 < 'a', '10' < '9', 1 = 1.0, 'a' = 'A', 2 > 1, 3 != 3, 2 == 2, 2 <> 3")
    def test_three_valued(self): self.check("SELECT NULL AND 0, NULL OR 1, NULL AND 1, NULL OR 0, NOT NULL, NOT 0, NOT 5")
    def test_not_precedence(self): self.check("SELECT NOT 1 = 2, 1 = 1 = 1, 1 < 2 = 1")
    def test_where_null_is_false(self): self.check("SELECT name FROM emp WHERE salary > 60000")
    def test_where_not_with_null(self): self.check("SELECT name FROM emp WHERE NOT (salary > 60000)")
    def test_is_null(self): self.check("SELECT name, dept IS NULL, salary IS NOT NULL FROM emp WHERE dept IS NULL OR salary IS NULL")
    def test_in_list(self): self.check("SELECT id FROM emp WHERE id IN (1, 3, 99)")
    def test_in_with_null(self): self.check("SELECT 3 IN (1, NULL), 1 IN (1, NULL), 3 NOT IN (1, NULL), NULL IN (1, 2), 3 NOT IN (1, 2)")
    def test_not_in_skips_null(self): self.check("SELECT name FROM emp WHERE dept NOT IN ('eng')")
    def test_between(self): self.check("SELECT name FROM emp WHERE salary BETWEEN 70000 AND 95000")
    def test_not_between(self): self.check("SELECT id FROM emp WHERE id NOT BETWEEN 2 AND 4")
    def test_like_prefix_any_case(self): self.check("SELECT name FROM emp WHERE name LIKE 'f%' OR name LIKE 'A%'")
    def test_like_underscore(self): self.check("SELECT name FROM emp WHERE name LIKE '_e_'")
    def test_not_like(self): self.check("SELECT name FROM emp WHERE name NOT LIKE '%E%'")
    def test_like_values(self): self.check("SELECT 'abc' LIKE 'A%', 'aBc' LIKE '_b_', NULL LIKE 'a', 'ab' LIKE 'a', 'a%c' LIKE 'a%c'")
    def test_number_truth(self): self.check("SELECT a FROM nums WHERE a")
    def test_text_truth(self): self.check("SELECT a FROM nums WHERE c")
    def test_and_or_mix(self): self.check("SELECT id FROM emp WHERE dept = 'eng' AND salary > 96000 OR boss = 3")


class Cases(Base):
    def test_searched_case(self):
        self.check("SELECT name, CASE WHEN salary >= 100000 THEN 'high' WHEN salary >= 70000 THEN 'mid' ELSE 'low' END FROM emp ORDER BY id")

    def test_simple_case(self): self.check("SELECT id, CASE dept WHEN 'eng' THEN 1 WHEN 'ops' THEN 2 END FROM emp ORDER BY id")
    def test_case_null_condition(self): self.check("SELECT CASE WHEN NULL THEN 1 ELSE 2 END, CASE 5 WHEN 1 THEN 'a' END")


class Functions(Base):
    def test_scalar_functions(self): self.check("SELECT ABS(-2.5), ABS(-3), LENGTH('héllo'), LENGTH(12.5), LENGTH(-3), UPPER('abc'), LOWER('ABC')")
    def test_upper_is_ascii_only(self): self.check("SELECT UPPER('aé'), LOWER('ÉA')")
    def test_substr(self): self.check("SELECT SUBSTR('hello', 2, 3), SUBSTR('hello', 2), SUBSTR(name, 1, 2) FROM emp WHERE id = 6")
    def test_null_helpers(self): self.check("SELECT COALESCE(NULL, NULL, 3), IFNULL(NULL, 'z'), NULLIF(3, 3), NULLIF(3, 4), COALESCE(dept, 'none') FROM emp WHERE id = 5")
    def test_round(self): self.check("SELECT ROUND(2.5), ROUND(-2.5), ROUND(0.125, 2), ROUND(7), ROUND(1234.5678, 2)")
    def test_typeof(self): self.check("SELECT TYPEOF(1), TYPEOF(1.5), TYPEOF('a'), TYPEOF(NULL), TYPEOF(1 / 2), TYPEOF(1 / 2.0), TYPEOF(ROUND(7))")
    def test_functions_of_null(self): self.check("SELECT ABS(NULL), UPPER(NULL), LENGTH(NULL), ROUND(NULL), SUBSTR(NULL, 1)")
    def test_functions_case_insensitive(self): self.check("SELECT upper(name), Length(name) FROM emp WHERE id = 1")


class Affinity(Base):
    def test_integer_column(self):
        self.check("SELECT i, TYPEOF(i) FROM t", "CREATE TABLE t (i INTEGER)",
                   "INSERT INTO t VALUES ('12'), ('3.0'), (2.0), ('1.5'), (' 4 '), ('abc'), (NULL), (2.5)")

    def test_real_column(self):
        self.check("SELECT r, TYPEOF(r) FROM t", "CREATE TABLE t (r REAL)", "INSERT INTO t VALUES ('7'), (7), ('1e2'), ('abc'), (2.5)")

    def test_text_column(self):
        self.check("SELECT s, TYPEOF(s) FROM t", "CREATE TABLE t (s TEXT)", "INSERT INTO t VALUES (12), (2.5), (1e3), ('x'), (NULL)")

    def test_untyped_column(self):
        self.check("SELECT u, TYPEOF(u) FROM t", "CREATE TABLE t (u)", "INSERT INTO t VALUES (2.0), ('5'), (3), ('x')")

    def test_fixture_values(self): self.check("SELECT salary, TYPEOF(salary) FROM emp ORDER BY id")
    def test_update_converts(self): self.after(["UPDATE nums SET a = '42' WHERE a = 7"], "SELECT a, TYPEOF(a) FROM nums WHERE a = 42")
    def test_insert_some_columns(self): self.after(["INSERT INTO dept (code) VALUES ('fin')"], "SELECT * FROM dept WHERE code = 'fin'")
    def test_insert_columns_in_any_order(self): self.after(["INSERT INTO dept (floor, code) VALUES ('2', 'fin')"], "SELECT code, title, floor, TYPEOF(floor) FROM dept WHERE code = 'fin'")


class Aggregates(Base):
    def test_counts(self): self.check("SELECT COUNT(*), COUNT(salary), COUNT(DISTINCT dept), COUNT(dept) FROM emp")
    def test_sum_avg_min_max(self): self.check("SELECT SUM(id), TYPEOF(SUM(id)), AVG(id), SUM(salary), MIN(salary), MAX(salary) FROM emp")
    def test_empty_table_aggregates(self): self.check("SELECT COUNT(*), SUM(id), AVG(id), MIN(id), MAX(name) FROM emp WHERE id > 100")
    def test_group_by(self): self.check("SELECT dept, COUNT(*), SUM(salary) FROM emp GROUP BY dept ORDER BY dept")
    def test_having(self): self.check("SELECT dept, COUNT(*) AS n FROM emp GROUP BY dept HAVING COUNT(*) > 1 ORDER BY n DESC, dept")
    def test_group_by_expression(self): self.check("SELECT salary > 80000, COUNT(*) FROM emp GROUP BY salary > 80000 ORDER BY 1")
    def test_avg_skips_null(self): self.check("SELECT dept, AVG(salary) FROM emp WHERE dept IS NOT NULL GROUP BY dept ORDER BY dept")
    def test_min_max_text(self): self.check("SELECT MIN(name), MAX(name) FROM emp")
    def test_aggregate_expressions(self): self.check("SELECT MAX(salary) - MIN(salary), COUNT(*) * 2, SUM(id * 10) FROM emp")
    def test_having_only(self): self.check("SELECT dept FROM emp GROUP BY dept HAVING MAX(salary) > 100000")
    def test_group_two_keys(self): self.check("SELECT dept, boss, COUNT(*) FROM emp GROUP BY dept, boss ORDER BY dept, boss")
    def test_sum_of_reals(self): self.check("SELECT SUM(b), AVG(b), TYPEOF(SUM(b)), COUNT(b) FROM nums")


class Ordering(Base):
    def test_nulls_first(self): self.check("SELECT name, salary FROM emp ORDER BY salary")
    def test_desc_nulls_last(self): self.check("SELECT name, salary FROM emp ORDER BY salary DESC")
    def test_mixed_types(self): self.check("SELECT d FROM nums ORDER BY d")
    def test_mixed_types_desc(self): self.check("SELECT d FROM nums ORDER BY d DESC")
    def test_several_keys(self): self.check("SELECT dept, name FROM emp ORDER BY dept DESC, name")
    def test_position_and_limit(self): self.check("SELECT name AS n, id FROM emp ORDER BY 2 DESC LIMIT 3")
    def test_expression_key(self): self.check("SELECT id FROM emp ORDER BY id % 3, id")
    def test_binary_text_order(self): self.check("SELECT name FROM emp ORDER BY name")
    def test_order_by_alias(self): self.check("SELECT id * -1 AS neg FROM emp ORDER BY neg")
    def test_limit_offset(self): self.check("SELECT id FROM emp ORDER BY id LIMIT 2 OFFSET 3")
    def test_limit_more_than_rows(self): self.check("SELECT id FROM emp ORDER BY id DESC LIMIT 10")
    def test_distinct(self): self.check("SELECT DISTINCT dept FROM emp ORDER BY dept")
    def test_distinct_rows(self): self.check("SELECT DISTINCT dept, boss FROM emp ORDER BY dept, boss")
    def test_order_by_column_not_selected(self): self.check("SELECT name FROM emp ORDER BY salary DESC, id")


class Joins(Base):
    def test_inner_join(self): self.check("SELECT e.name, d.title FROM emp e JOIN dept d ON e.dept = d.code ORDER BY e.id")
    def test_left_join(self): self.check("SELECT e.name, d.title FROM emp e LEFT JOIN dept d ON e.dept = d.code ORDER BY e.id")
    def test_left_join_missing(self): self.check("SELECT d.code FROM dept d LEFT JOIN emp e ON e.dept = d.code WHERE e.id IS NULL")
    def test_self_join(self): self.check("SELECT e.name, b.name FROM emp e JOIN emp b ON e.boss = b.id ORDER BY e.id")
    def test_join_group(self): self.check("SELECT d.title, COUNT(e.id) FROM dept d LEFT JOIN emp e ON e.dept = d.code GROUP BY d.title ORDER BY d.title")
    def test_three_tables(self): self.check("SELECT e.name, b.name, d.floor FROM emp e JOIN emp b ON e.boss = b.id JOIN dept d ON d.code = b.dept ORDER BY e.id")
    def test_inner_keyword_unqualified(self): self.check("SELECT COUNT(*) FROM emp INNER JOIN dept ON dept = code")
    def test_unqualified_unique_columns(self): self.check("SELECT name, title FROM emp JOIN dept ON dept = code WHERE floor = 1 ORDER BY name")
    def test_left_outer_keyword(self): self.check("SELECT d.title, e.name FROM dept d LEFT OUTER JOIN emp e ON e.dept = d.code AND e.salary > 90000 ORDER BY d.title, e.name")
    def test_join_star(self): self.check("SELECT * FROM dept d JOIN emp e ON e.dept = d.code WHERE e.id = 3")


class Changes(Base):
    def test_update(self):
        self.after(["UPDATE emp SET salary = salary * 2, name = UPPER(name) WHERE dept = 'ops'"], "SELECT name, salary FROM emp WHERE dept = 'ops' ORDER BY id")

    def test_update_uses_old_values(self): self.after(["UPDATE nums SET a = b, b = a WHERE a = 7"], "SELECT a, b, TYPEOF(a), TYPEOF(b) FROM nums WHERE c = 'x'")
    def test_update_all_rows(self): self.after(["UPDATE dept SET floor = floor + 1"], "SELECT code, floor FROM dept ORDER BY code")
    def test_delete_where(self): self.after(["DELETE FROM emp WHERE salary < 80000"], "SELECT id FROM emp ORDER BY id")
    def test_delete_all(self): self.after(["DELETE FROM dept"], "SELECT COUNT(*) FROM dept")
    def test_drop_and_create(self): self.after(["DROP TABLE dept", "CREATE TABLE dept (x)", "INSERT INTO dept VALUES (1)"], "SELECT * FROM dept")


class Errors(Base):
    def test_unknown_table(self): self.fails("SELECT * FROM nope", "INSERT INTO nope VALUES (1)", "DROP TABLE nope")
    def test_unknown_column(self): self.fails("SELECT nope FROM emp", "SELECT id FROM emp WHERE nope = 1", "UPDATE emp SET nope = 1")
    def test_ambiguous_column(self): self.fails("SELECT id FROM emp e JOIN emp b ON e.boss = b.id")
    def test_table_exists(self): self.fails("CREATE TABLE emp (x)")
    def test_wrong_value_count(self): self.fails("INSERT INTO dept VALUES ('a', 'b')", "INSERT INTO dept (code, title) VALUES ('a')")
    def test_syntax(self): self.fails("SELEC 1", "SELECT FROM emp", "SELECT id FROM emp WHERE", "SELECT (1 + 2")
    def test_aggregate_in_where(self): self.fails("SELECT name FROM emp WHERE COUNT(*) > 1")


class Speed(Base):
    def test_thousands_of_rows(self):
        rows = ", ".join(f"({i}, {i * 7 % 1000}, 'n{i % 50}')" for i in range(4000))
        start = time.time()
        self.check("SELECT k % 10, COUNT(*), SUM(v), MAX(t) FROM big GROUP BY k % 10 ORDER BY 1",
                   "CREATE TABLE big (k INTEGER, v INTEGER, t TEXT)", f"INSERT INTO big VALUES {rows}")
        self.assertLess(time.time() - start, 8)

    def test_join_of_500(self):
        a = ", ".join(f"({i}, {i % 37})" for i in range(500))
        b = ", ".join(f"({i % 37}, 'g{i}')" for i in range(500))
        start = time.time()
        self.check("SELECT COUNT(*), COUNT(DISTINCT x.id) FROM x JOIN y ON x.g = y.g",
                   "CREATE TABLE x (id INTEGER, g INTEGER)", f"INSERT INTO x VALUES {a}",
                   "CREATE TABLE y (g INTEGER, name TEXT)", f"INSERT INTO y VALUES {b}")
        self.assertLess(time.time() - start, 20)


if __name__ == "__main__":
    unittest.main()
