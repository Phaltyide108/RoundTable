Build a small SQL database engine in Python (standard library only) whose answers match SQLite's for the subset of SQL below. The tests import `minisql.py`; you may split the code into more modules next to it. Do not use `sqlite3`, `ctypes` or any other database or native code: hidden tests compare your engine with real SQLite, and code that imports them scores 0. Write your own tests too.

## API

```python
from minisql import Database, SQLError
db = Database()
db.execute("CREATE TABLE t (id INTEGER, name TEXT, score REAL)")    # -> []
db.execute("INSERT INTO t VALUES (1, 'ann', 9.5), (2, 'bob', NULL)")  # -> []
db.execute("SELECT name, score FROM t WHERE id = 1")                 # -> [('ann', 9.5)]
```

`execute(sql)` runs one statement (a trailing `;` is allowed) and returns a list of tuples, one per row (`[]` for statements that return no rows). Values are `int`, `float`, `str` or `None` (NULL). Every error (bad syntax, unknown table or column, an ambiguous column, a table that already exists, a wrong number of values, an aggregate in WHERE) raises `SQLError`, a subclass of `Exception`. Keywords, function names, table and column names are case-insensitive; string values are case-sensitive.

## Statements

- `CREATE TABLE name (col TYPE, ...)`: TYPE is `INTEGER`, `REAL`, `TEXT` or left out. `DROP TABLE name`.
- `INSERT INTO name [(col, ...)] VALUES (...), (...)`: columns left out are NULL.
- `UPDATE name SET col = expr [, ...] [WHERE cond]`: every expression sees the row's values from before the update.
- `DELETE FROM name [WHERE cond]`.
- `SELECT [DISTINCT] items [FROM source] [WHERE cond] [GROUP BY expr, ...] [HAVING cond] [ORDER BY expr [ASC|DESC], ...] [LIMIT n [OFFSET m]]`
  - items: `*` (every column of every table, in FROM order), `alias.*`, or expressions, each optionally followed by `AS name` (or just a name).
  - source: a table with an optional alias (`emp e` or `emp AS e`), then any number of `[INNER] JOIN t [alias] ON cond` or `LEFT [OUTER] JOIN t [alias] ON cond` (a left join keeps every left row; missing right columns are NULL). A column is written `col` or `alias.col`; a bare name found in more than one table of the query is an error.
  - Without FROM the items are evaluated once: `SELECT 1 + 1` gives `[(2,)]`.
  - ORDER BY takes an expression, an output column name (`AS` name), or a 1-based output position (`ORDER BY 2`).
  - Without ORDER BY the row order does not matter.

## Values and types

- Literals: integers (`42`), reals (`2.5`, `.5`, `2.50`; `1e3` is the real 1000.0), strings in single quotes (`'it''s'` is `it's`), `NULL`.
- Column types convert values on INSERT and UPDATE:
  - INTEGER: text that looks like a number (spaces around it allowed) becomes that number: `'12'` gives 12, `' 4 '` gives 4, `'1.5'` gives 1.5, `'3.0'` gives 3; a real with no fraction becomes an int (2.0 gives 2). Everything else is kept as it is (`'abc'` stays text, 2.5 stays 2.5).
  - REAL: ints and text that looks like a number become floats (7 gives 7.0, `'7'` gives 7.0, `'1e2'` gives 100.0); other text stays text.
  - TEXT: numbers become text the way Python's `str()` writes them (12 gives `'12'`, 2.5 gives `'2.5'`, 1e3 gives `'1000.0'`).
  - No type: values are kept exactly as given (2.0 stays 2.0, `'5'` stays text).
- Arithmetic `+ - * / %`: two ints give an int; `/` on two ints truncates toward zero (`-7 / 2` is -3); `%` on two ints takes the sign of the left side (`-7 % 3` is -1, `7 % -3` is 1); if either side of `%` is real, both sides are first truncated to ints and the result is a real (`10 % 3.5` is 1.0). Otherwise a real on either side gives a real (`7 / 2.0` is 3.5). Dividing (or `%`) by zero gives NULL. Any NULL operand gives NULL. Text in arithmetic uses the number it starts with (`'12abc' + 0` is 12, `'2.5' + 1` is 3.5, `'abc' + 1` is 1, `'3' * '4'` is the int 12).
- `a || b` joins as text: numbers are written as Python's `str()` writes them (`2.0 || ''` is `'2.0'`, `3 || 'x'` is `'3x'`); a NULL on either side gives NULL.
- Comparisons `=`, `==`, `!=`, `<>`, `<`, `<=`, `>`, `>=` give 1 or 0, or NULL when either side is NULL. Numbers compare by value (`1 = 1.0` is 1). Text compares by code point, case-sensitively (`'a' = 'A'` is 0, `'10' < '9'` is 1). A number is always less than a text (`1 < 'a'` is 1); the tests never compare a number with a text that looks like a number.
- A condition (in WHERE, HAVING, ON, CASE WHEN) holds when its value is a non-zero number; text counts as the number it starts with (`'10'` holds, `'x'` and `''` do not); NULL and 0 do not hold.
- `AND`, `OR`, `NOT` use three-valued logic: `NULL AND 0` is 0, `NULL AND 1` is NULL, `NULL OR 1` is 1, `NOT NULL` is NULL, `NOT 5` is 0.
- `x IS NULL` and `x IS NOT NULL` give 1 or 0. `x IN (a, b, ...)` is 1 when x equals one of them; otherwise NULL if x or any list value is NULL, else 0; `NOT IN` is its negation (NULL stays NULL). `x BETWEEN a AND b` means `x >= a AND x <= b`; `NOT BETWEEN` negates it. `x LIKE p`: in p, `%` matches any run of characters and `_` exactly one; ASCII letters match regardless of case; NULL on either side gives NULL; `NOT LIKE` negates it.
- `CASE WHEN c THEN v [WHEN ...] [ELSE e] END` and `CASE x WHEN a THEN v [WHEN ...] [ELSE e] END`: the first match wins; with no match and no ELSE the result is NULL.
- Precedence, tightest first: unary `-` and `+`; `||`; `* / %`; `+ -`; `< <= > >=`; `= == != <> IS IN LIKE BETWEEN`; `NOT`; `AND`; `OR`. Binary operators of the same level group left to right (`1 = 1 = 1` is 1; `2 || 3 * 4` is `('2' || '3') * 4`, which is 92; `NOT 1 = 2` is 1). Parentheses group.

## Functions

- `ABS(x)`; `LENGTH(x)` (characters; for a number, the length of its text: `LENGTH(12.5)` is 4); `UPPER(s)`, `LOWER(s)` (ASCII letters only); `SUBSTR(s, start [, n])` (1-based: `SUBSTR('hello', 2, 3)` is `'ell'`); `ROUND(x [, digits])` returns a real, halves away from zero (`ROUND(2.5)` is 3.0, `ROUND(-2.5)` is -3.0, `ROUND(7)` is 7.0, `ROUND(0.125, 2)` is 0.13); `TYPEOF(x)` gives `'integer'`, `'real'`, `'text'` or `'null'`. These give NULL when an argument is NULL (except TYPEOF).
- `COALESCE(a, b, ...)` (first non-NULL), `IFNULL(a, b)`, `NULLIF(a, b)` (NULL when a = b, else a).
- Aggregates: `COUNT(*)` (rows), `COUNT(x)` (non-NULL values), `COUNT(DISTINCT x)`, `SUM(x)` (an int when all values are ints, else a real; NULL when there are no non-NULL values), `AVG(x)` (a real; NULL when none), `MIN(x)` and `MAX(x)` (skip NULLs; order as in ORDER BY). An aggregate's argument may be any expression and aggregates may appear inside expressions (`MAX(a) - MIN(a)`).
- A SELECT with aggregates and no GROUP BY gives exactly one row, even when no rows match (`SELECT COUNT(*) FROM t WHERE 0` gives `[(0,)]`). With GROUP BY, it gives one row per group of equal values (all NULLs form one group). Next to aggregates the tests only select expressions that are in the GROUP BY. HAVING keeps the groups whose condition holds and may use aggregates. An aggregate in WHERE is an error.

## Ordering, DISTINCT and LIMIT

- ORDER BY sorts NULLs first, then numbers (by value), then text (by code point); DESC reverses all of that, so NULLs come last. Later keys break ties of earlier ones; the tests always give enough keys for one order.
- DISTINCT removes duplicate rows (NULLs count as equal to each other).
- `LIMIT n` keeps the first n rows after ordering; `OFFSET m` skips m rows first.

## Speed

A table of a few thousand rows must insert, group and sort in well under a second; joining two tables of 500 rows each must take a few seconds at most.
