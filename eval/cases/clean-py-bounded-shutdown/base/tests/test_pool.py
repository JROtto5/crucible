import unittest

from workers.pool import Pool


class PoolTest(unittest.TestCase):
    def test_shutdown_after_quick_jobs(self):
        p = Pool()
        out = []
        p.submit(lambda: out.append(1))
        p.shutdown()
        self.assertEqual(out, [1])


if __name__ == "__main__":
    unittest.main()
