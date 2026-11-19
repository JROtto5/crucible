import unittest

from scorer import rank, top


class RankTest(unittest.TestCase):
    def test_best_first(self):
        self.assertEqual(rank([12.0, 40.5, 33.0]), [1, 2, 0])

    def test_top(self):
        self.assertEqual(top([5, 1, 9, 7], n=2), [2, 3])


if __name__ == "__main__":
    unittest.main()
