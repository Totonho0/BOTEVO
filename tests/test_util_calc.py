import unittest

from cogs.util import _safe_eval_expr


class TestSafeCalculator(unittest.TestCase):
    def test_basic_ops(self):
        self.assertEqual(_safe_eval_expr("2+3*4"), 14)
        self.assertEqual(_safe_eval_expr("(10-2)%3"), 2)

    def test_unary(self):
        self.assertEqual(_safe_eval_expr("-5+2"), -3)

    def test_reject_non_numeric_nodes(self):
        with self.assertRaises(ValueError):
            _safe_eval_expr("__import__('os').system('echo x')")


if __name__ == "__main__":
    unittest.main()
