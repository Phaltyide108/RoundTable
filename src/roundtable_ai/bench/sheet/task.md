Build a small spreadsheet engine in Python (standard library only) in the file `sheet.py`. Keep the public API exactly as described; hidden tests will check it. Write your own tests too.

## API

```python
from sheet import Sheet
s = Sheet()
s.set("A1", 5)            # numbers (int or float)
s.set("A2", "hello")      # text
s.set("A3", "=A1*2+1")    # a formula starts with "="
s.get("A3")               # -> 11 (the evaluated value, recalculated whenever an input changes)
s.set("A1", None)         # empties a cell
s.formula("A3")           # -> "=A1*2+1" (or the raw value for non-formula cells, None when empty)
s.dependents("A1")        # -> every cell that depends on A1, directly or not, e.g. ["A3"],
                          #    sorted by column then row: A2, A10, B1, AA1
```

Cell names are a column of one or two letters A..ZZ followed by a row 1..9999, case-insensitive (`a1` is `A1`). `set`, `get`, `formula` and `dependents` raise `ValueError` for an invalid cell name.

## Values

- An empty cell reads as `None` from `get`, as 0 in arithmetic and comparisons with numbers, and as "" in text joins.
- Results that are whole numbers are returned as `int` (e.g. `=4/2` gives `2`), others as `float`.
- Text values are returned as `str`. Booleans from comparisons are returned as `True`/`False`.

## Formulas

- Numbers (`3`, `2.5`, `.5`), text in double quotes (`"a b"`; `""` inside a string is one quote), `TRUE`, `FALSE`.
- Cell references (`B7`) and ranges (`A1:B3`, any two corners) — ranges only as function arguments. A formula depends on every cell it names, including every cell inside its ranges.
- Operators, from lowest to highest precedence: comparisons `= <> < > <= >=`; text join `&`; `+ -`; `* /`; `^` (power, right-associative: `2^3^2` is 512); unary `-` and `+` bind tighter than `* /` but looser than `^` (`-2^2` is -4). Parentheses group.
- Comparing two numbers or two texts works as expected (text compares case-insensitively). Comparing a number with a text gives `#VALUE!`.
- Functions (names case-insensitive): `SUM`, `MIN`, `MAX`, `AVERAGE`, `COUNT` take any mix of numbers, cells and ranges; in ranges they skip empty and text cells (`COUNT` counts numbers only; `AVERAGE` of no numbers is `#DIV/0!`; `MIN`/`MAX` of no numbers is 0). `IF(cond, then, else)` evaluates only the branch it picks; `else` may be omitted (then it gives `FALSE`). `CONCAT(...)` joins any number of values as text. `LEN(text)`, `UPPER(text)`, `LOWER(text)`, `ROUND(number, digits)` (half away from zero, as the number is written in decimal: `ROUND(1.005, 2)` is 1.01; negative digits round to tens, hundreds...), `ABS(number)`.
- `TRUE` is 1 and `FALSE` is 0 in arithmetic. Text that looks like a number is still text: `="3"+1` is `#VALUE!`.
- Text joined with `&`: numbers are shown without a trailing `.0` (`=1.0&""` is `"1"`), booleans as `TRUE`/`FALSE`.

## Errors

Errors are returned from `get` as these strings and spread through any formula that uses them (the first error met, left to right, wins; `IF` only spreads errors from the branch it picks or from its condition):

- `#DIV/0!` division by zero
- `#VALUE!` wrong type (text in arithmetic, number compared with text, wrong number of arguments to a function)
- `#NAME?` unknown function name, or a bad name in a formula
- `#REF!` a reference to an invalid cell name (e.g. `=A0` or `=AAA1`)
- `#CYCLE!` a cell that is part of, or depends on, a circular reference (decided by the cells a formula names, whichever `IF` branch runs)
- `#ERROR!` a formula that cannot be parsed (e.g. `=1+`, `=(1`, `=1 2`)

`set` never raises for a bad formula: the cell just evaluates to the error. Cycles must not crash or hang, and fixing a cycle (changing one of its cells) must make every cell in it evaluate normally again.

## Performance

A chain of 2000 cells (`A2 = A1+1`, `A3 = A2+1`, ...) must evaluate without hitting Python's recursion limit, and changing `A1` then reading the last cell must take well under a second.
