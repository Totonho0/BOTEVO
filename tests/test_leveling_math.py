import unittest

from cogs.leveling import level_from_xp, xp_for_level


class TestLevelingMath(unittest.TestCase):
    def test_curve_monotonic(self):
        prev = 0
        for level in range(1, 30):
            req = xp_for_level(level)
            self.assertGreater(req, prev)
            prev = req

    def test_inverse_behavior(self):
        self.assertEqual(level_from_xp(0), 0)
        self.assertEqual(level_from_xp(xp_for_level(1) - 1), 0)
        self.assertEqual(level_from_xp(xp_for_level(1)), 1)
        self.assertEqual(level_from_xp(xp_for_level(5)), 5)


if __name__ == "__main__":
    unittest.main()
