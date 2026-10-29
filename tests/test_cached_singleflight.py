import threading
import time
import unittest

import app as app_module
from app import cache


class CachedSingleFlightTest(unittest.TestCase):
    def setUp(self):
        pass

    def test_concurrent_misses_run_producer_once(self):
        calls = []
        gate = threading.Event()

        def producer():
            calls.append(1)
            gate.wait(2)
            return {'ok': True}

        key = 'sf_test_concurrent'
        results = []

        def worker():
            results.append(app_module.cached(key, producer, ttl=60))

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        time.sleep(0.2)  # beri waktu semua thread menumpuk di lock
        gate.set()
        for t in threads:
            t.join(5)

        self.assertEqual(len(calls), 1, 'producer harus jalan sekali untuk key yang sama')
        self.assertEqual(len(results), 6)
        self.assertTrue(all(r == {'ok': True} for r in results))

    def test_different_keys_do_not_block_each_other(self):
        started = threading.Event()

        def slow():
            started.wait(2)
            return 1

        t = threading.Thread(target=lambda: app_module.cached('sf_slow', slow, ttl=60))
        t.start()
        # key lain harus tetap jalan walau 'sf_slow' sedang menunggu.
        out = app_module.cached('sf_fast', lambda: 2, ttl=60)
        started.set()
        t.join(5)
        self.assertEqual(out, 2)

    def test_failed_producer_releases_lock_for_next_caller(self):
        import requests

        def boom():
            raise requests.ConnectionError('down')

        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            app_module.cached('sf_fail', boom, ttl=60)
        # Pemanggil berikutnya tidak boleh macet pada lock yang tertinggal.
        self.assertEqual(app_module.cached('sf_fail', lambda: 'recovered', ttl=60), 'recovered')


if __name__ == '__main__':
    unittest.main()
