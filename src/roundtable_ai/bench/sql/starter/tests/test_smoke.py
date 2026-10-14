import unittest


class Smoke(unittest.TestCase):
    def test_import(self):
        from minisql import Database, SQLError  # noqa: F401


if __name__ == "__main__":
    unittest.main()
