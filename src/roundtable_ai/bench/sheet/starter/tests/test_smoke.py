import unittest


class Smoke(unittest.TestCase):
    def test_import(self):
        from sheet import Sheet  # noqa: F401


if __name__ == "__main__":
    unittest.main()
