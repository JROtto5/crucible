import threading
import unittest

from workers.pool import Pool


class PoolTest(unittest.TestCase):
    def test_shutdown_after_quick_jobs(self):
        p = Pool()
        out = []
        p.submit(lambda: out.append(1))
        self.assertTrue(p.shutdown())
        self.assertEqual(out, [1])

    def test_shutdown_returns_with_a_stuck_job(self):
        p = Pool()
        stop = threading.Event()
        p.submit(stop.wait)
        try:
            self.assertFalse(p.shutdown(timeout=0.2))
        finally:
            stop.set()


if __name__ == "__main__":
    unittest.main()
