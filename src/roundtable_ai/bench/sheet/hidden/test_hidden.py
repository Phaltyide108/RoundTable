"""Hidden tests for the `sheet` benchmark task (standard library unittest only).
Each test checks one rule of TASK.md, so the score shows which parts work."""

import time
import unittest

from sheet import Sheet


def sheet(**cells):
    s = Sheet()
    for k, v in cells.items():
        s.set(k, v)
    return s


class Values(unittest.TestCase):
    def test_numbers_and_text(self):
        s = sheet(A1=5, A2="hello", A3=2.5)
        self.assertEqual(s.get("A1"), 5)
        self.assertEqual(s.get("A2"), "hello")
        self.assertEqual(s.get("A3"), 2.5)

    def test_empty_cell_is_none(self):
        self.assertIsNone(Sheet().get("B7"))

    def test_clearing_a_cell(self):
        s = sheet(A1=5, A2="=A1+1")
        s.set("A1", None)
        self.assertIsNone(s.get("A1"))
        self.assertEqual(s.get("A2"), 1)

    def test_case_insensitive_names(self):
        s = Sheet()
        s.set("b2", 7)
        self.assertEqual(s.get("B2"), 7)
        s.set("C1", "=b2*2")
        self.assertEqual(s.get("c1"), 14)

    def test_invalid_names_raise(self):
        s = Sheet()
        for bad in ("A0", "1A", "AAA1", "A10000", "", "A1B"):
            with self.assertRaises(ValueError, msg=bad):
                s.set(bad, 1)
            with self.assertRaises(ValueError, msg=bad):
                s.get(bad)

    def test_two_letter_columns(self):
        s = sheet(ZZ9999=3, AB12="=ZZ9999+1")
        self.assertEqual(s.get("AB12"), 4)

    def test_formula_returns_raw(self):
        s = sheet(A1=5, A3="=A1*2+1", A4="text")
        self.assertEqual(s.formula("A3"), "=A1*2+1")
        self.assertEqual(s.formula("A1"), 5)
        self.assertEqual(s.formula("A4"), "text")
        self.assertIsNone(s.formula("A9"))


class Arithmetic(unittest.TestCase):
    def check(self, formula, expected, **cells):
        s = sheet(**cells)
        s.set("Z1", formula)
        got = s.get("Z1")
        self.assertEqual(got, expected, formula)
        self.assertEqual(type(got), type(expected), formula)

    def test_precedence(self):
        self.check("=1+2*3", 7)
        self.check("=(1+2)*3", 9)
        self.check("=10-4-3", 3)
        self.check("=2*3^2", 18)

    def test_power_is_right_associative(self):
        self.check("=2^3^2", 512)

    def test_unary_minus(self):
        self.check("=-2^2", -4)
        self.check("=-(3)*-2", 6)
        self.check("=2^-1", 0.5)

    def test_whole_results_are_int(self):
        self.check("=4/2", 2)
        self.check("=7/2", 3.5)
        self.check("=0.5+0.5", 1)

    def test_decimal_literals(self):
        self.check("=.5*4", 2)

    def test_cell_references_and_recalculation(self):
        s = sheet(A1=2, B1="=A1*10", C1="=B1+A1")
        self.assertEqual(s.get("C1"), 22)
        s.set("A1", 3)
        self.assertEqual(s.get("C1"), 33)

    def test_empty_is_zero(self):
        self.check("=A9+1", 1)

    def test_booleans_in_arithmetic(self):
        self.check("=TRUE+TRUE", 2)

    def test_text_in_arithmetic_is_value_error(self):
        self.check("=A1+1", "#VALUE!", A1="x")
        self.check('="3"+1', "#VALUE!")

    def test_divide_by_zero(self):
        self.check("=1/0", "#DIV/0!")
        self.check("=1/A9", "#DIV/0!")


class Text(unittest.TestCase):
    def check(self, formula, expected, **cells):
        s = sheet(**cells)
        s.set("Z1", formula)
        self.assertEqual(s.get("Z1"), expected, formula)

    def test_strings_and_quotes(self):
        self.check('="a b"', "a b")
        self.check('="say ""hi"""', 'say "hi"')

    def test_join(self):
        self.check('="n="&A1', "n=4", A1=4)
        self.check('=1.0&""', "1")
        self.check('=2.5&"x"', "2.5x")
        self.check('=TRUE&""', "TRUE")
        self.check('=A9&"!"', "!")

    def test_join_is_below_arithmetic(self):
        self.check('=1+2&3', "33")

    def test_text_functions(self):
        self.check('=UPPER("abc")', "ABC")
        self.check('=lower("ABC")', "abc")
        self.check('=LEN("hello")', 5)
        self.check('=CONCAT("a", 1, TRUE, A1)', "a1TRUEz", A1="z")


class Comparisons(unittest.TestCase):
    def check(self, formula, expected, **cells):
        s = sheet(**cells)
        s.set("Z1", formula)
        self.assertEqual(s.get("Z1"), expected, formula)

    def test_numbers(self):
        self.check("=1<2", True)
        self.check("=2<=1", False)
        self.check("=3=3", True)
        self.check("=3<>3", False)

    def test_comparison_is_lowest(self):
        self.check("=1+1=2", True)

    def test_text_case_insensitive(self):
        self.check('="abc"="ABC"', True)
        self.check('="a"<"b"', True)

    def test_mixed_types(self):
        self.check('=1="1"', "#VALUE!")

    def test_empty_compares_as_zero(self):
        self.check("=A9=0", True)


class Functions(unittest.TestCase):
    def setUp(self):
        self.s = sheet(A1=1, A2=2, A3="x", A4=None, B1=4, B2=5.5)

    def val(self, formula):
        self.s.set("Z1", formula)
        return self.s.get("Z1")

    def test_sum_ranges_skip_text_and_empty(self):
        self.assertEqual(self.val("=SUM(A1:A4)"), 3)
        self.assertEqual(self.val("=SUM(A1:B2)"), 12.5)
        self.assertEqual(self.val("=SUM(B2:A1)"), 12.5)

    def test_mixed_arguments(self):
        self.assertEqual(self.val("=SUM(A1, 10, B1:B2)"), 20.5)

    def test_min_max_average_count(self):
        self.assertEqual(self.val("=MIN(A1:B2)"), 1)
        self.assertEqual(self.val("=MAX(A1:B2)"), 5.5)
        self.assertEqual(self.val("=AVERAGE(A1:A4)"), 1.5)
        self.assertEqual(self.val("=COUNT(A1:B2)"), 4)

    def test_empty_aggregates(self):
        self.assertEqual(self.val("=MIN(C1:C3)"), 0)
        self.assertEqual(self.val("=AVERAGE(C1:C3)"), "#DIV/0!")
        self.assertEqual(self.val("=SUM(C1:C3)"), 0)

    def test_function_names_case_insensitive(self):
        self.assertEqual(self.val("=sum(A1:A2)"), 3)

    def test_if(self):
        self.assertEqual(self.val('=IF(A1>0, "pos", "neg")'), "pos")
        self.assertEqual(self.val("=IF(A1>5, 1)"), False)
        self.assertEqual(self.val("=IF(0, 1, 2)"), 2)

    def test_if_evaluates_only_the_chosen_branch(self):
        self.assertEqual(self.val("=IF(TRUE, 1, 1/0)"), 1)
        self.assertEqual(self.val("=IF(FALSE, 1/0, 2)"), 2)
        self.assertEqual(self.val("=IF(1/0, 1, 2)"), "#DIV/0!")

    def test_round_half_away_from_zero(self):
        self.assertEqual(self.val("=ROUND(2.5, 0)"), 3)
        self.assertEqual(self.val("=ROUND(-2.5, 0)"), -3)
        self.assertEqual(self.val("=ROUND(1.005, 2)"), 1.01)
        self.assertEqual(self.val("=ROUND(1234, -2)"), 1200)

    def test_abs(self):
        self.assertEqual(self.val("=ABS(-3)"), 3)

    def test_wrong_argument_count(self):
        self.assertEqual(self.val("=ABS(1, 2)"), "#VALUE!")
        self.assertEqual(self.val("=IF(1)"), "#VALUE!")

    def test_unknown_function(self):
        self.assertEqual(self.val("=NOPE(1)"), "#NAME?")

    def test_nested(self):
        self.assertEqual(self.val('=IF(SUM(A1:A2)=3, UPPER(CONCAT("o", "k")), "no")'), "OK")


class Errors(unittest.TestCase):
    def val(self, formula, **cells):
        s = sheet(**cells)
        s.set("Z1", formula)
        return s.get("Z1")

    def test_parse_errors(self):
        for bad in ("=1+", "=(1", "=1 2", "=)", "=", "=1+*2", '="open'):
            self.assertEqual(self.val(bad), "#ERROR!", bad)

    def test_set_never_raises_for_bad_formulas(self):
        s = Sheet()
        s.set("A1", "=((")
        self.assertEqual(s.get("A1"), "#ERROR!")

    def test_bad_names(self):
        self.assertEqual(self.val("=foo+1"), "#NAME?")

    def test_bad_references(self):
        self.assertEqual(self.val("=A0+1"), "#REF!")
        self.assertEqual(self.val("=AAA1"), "#REF!")

    def test_errors_spread(self):
        s = sheet(A1="=1/0", A2="=A1+1", A3='=A2&"x"', A4="=SUM(A1:A2)")
        for c in ("A2", "A3", "A4"):
            self.assertEqual(s.get(c), "#DIV/0!", c)

    def test_first_error_wins(self):
        self.assertEqual(self.val('=(1/0)+("a"+1)'), "#DIV/0!")
        self.assertEqual(self.val('=("a"+1)+(1/0)'), "#VALUE!")


class Cycles(unittest.TestCase):
    def test_self_reference(self):
        s = sheet(A1="=A1+1")
        self.assertEqual(s.get("A1"), "#CYCLE!")

    def test_cycle_and_dependents(self):
        s = sheet(A1="=B1", B1="=A1", C1="=A1+1", D1=5)
        self.assertEqual(s.get("A1"), "#CYCLE!")
        self.assertEqual(s.get("B1"), "#CYCLE!")
        self.assertEqual(s.get("C1"), "#CYCLE!")
        self.assertEqual(s.get("D1"), 5)

    def test_cycle_through_a_range(self):
        s = sheet(A1=1, A2="=SUM(A1:A3)")
        self.assertEqual(s.get("A2"), "#CYCLE!")

    def test_fixing_a_cycle(self):
        s = sheet(A1="=B1", B1="=A1", C1="=A1+1")
        self.assertEqual(s.get("C1"), "#CYCLE!")
        s.set("B1", 5)
        self.assertEqual(s.get("A1"), 5)
        self.assertEqual(s.get("C1"), 6)

    def test_long_cycle_does_not_hang(self):
        s = Sheet()
        for i in range(1, 300):
            s.set(f"A{i}", f"=A{i + 1}")
        s.set("A300", "=A1")
        self.assertEqual(s.get("A150"), "#CYCLE!")


class Dependents(unittest.TestCase):
    def test_direct_and_indirect(self):
        s = sheet(A1=1, A2="=A1", A10="=A2", B1="=SUM(A1:A3)", AA1="=B1", C5=3)
        self.assertEqual(s.dependents("A1"), ["A2", "A10", "B1", "AA1"])
        self.assertEqual(s.dependents("A10"), [])

    def test_follows_changes(self):
        s = sheet(A1=1, A2="=A1")
        s.set("A2", 5)
        self.assertEqual(s.dependents("A1"), [])


class Performance(unittest.TestCase):
    def test_long_chain(self):
        s = Sheet()
        s.set("A1", 0)
        for i in range(2, 2001):
            s.set(f"A{i}", f"=A{i - 1}+1")
        self.assertEqual(s.get("A2000"), 1999)
        t = time.time()
        s.set("A1", 10)
        self.assertEqual(s.get("A2000"), 2009)
        self.assertLess(time.time() - t, 1.0)


if __name__ == "__main__":
    unittest.main()
