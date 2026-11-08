import unittest

from workers.pool import Pool


class PoolTest(unittest.TestCase):
    def test_shutdown_after_quick_jobs(self):
        p = Pool()
        out = []
        p.submit(lambda: out.append(1))
        self.assertTrue(p.shutdown())
        self.assertEqual(out, [1])

    def test_shutdown_takes_a_timeout(self):
        p = Pool()
        p.submit(lambda: None)
        self.assertTrue(p.shutdown(timeout=0.5))


if __name__ == "__main__":
    unittest.main()
