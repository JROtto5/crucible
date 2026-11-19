import unittest

from scorer import Settings, rank, top


class RankTest(unittest.TestCase):
    def test_best_first(self):
        self.assertEqual(rank({"ann": 12.0, "bo": 40.5, "cy": 33.0}), ["bo", "cy", "ann"])

    def test_top(self):
        self.assertEqual(top({"a": 5, "b": 1, "c": 9, "d": 7}, n=2), ["c", "d"])

    def test_min_score(self):
        self.assertEqual(rank({"a": 5, "b": 1}, Settings(min_score=2)), ["a"])
        self.assertEqual(rank({"a": -1, "b": 1}), ["b", "a"])

    def test_strict_missing(self):
        with self.assertRaises(ValueError):
            rank({"a": 5, "b": None}, Settings(strict=True))


if __name__ == "__main__":
    unittest.main()
