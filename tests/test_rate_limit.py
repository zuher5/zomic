import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from app import app


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        app_module._RATE_BUCKETS.clear()
        self.client = TestClient(app, client=("203.0.113.9", 50000))

    def tearDown(self):
        app_module._RATE_BUCKETS.clear()

    def _api_limit(self, limit=3):
        return patch.object(app_module, 'RATE_LIMIT_API', limit)

    def test_spoofed_forwarded_header_does_not_reset_bucket(self):
        # Peer tidak tepercaya: header palsu harus diabaikan.
        with self._api_limit(3):
            codes = []
            for i in range(5):
                r = self.client.get('/api/latest', headers={'X-Forwarded-For': f'198.51.100.{i}'})
                codes.append(r.status_code)
        self.assertIn(429, codes)

    def test_trusted_proxy_uses_forwarded_client_ip(self):
        # Peer tepercaya (loopback): IP klien diambil dari header proxy,
        # jadi dua klien berbeda punya bucket berbeda.
        tc = TestClient(app, client=("127.0.0.1", 50000))
        with self._api_limit(1), patch.object(app_module.cache, 'get', return_value=None):
            a1 = tc.get('/api/a', headers={'CF-Connecting-IP': '198.51.100.1'})
            a2 = tc.get('/api/a', headers={'CF-Connecting-IP': '198.51.100.1'})
            b1 = tc.get('/api/a', headers={'CF-Connecting-IP': '198.51.100.2'})
        self.assertEqual(a2.status_code, 429)
        self.assertNotEqual(b1.status_code, 429)
        self.assertNotEqual(a1.status_code, 429)

    def test_api_routes_share_one_bucket_per_ip(self):
        with self._api_limit(2), patch.object(app_module.cache, 'get', return_value=None):
            codes = [self.client.get(p).status_code for p in
                     ('/api/a', '/api/b', '/api/c')]
        self.assertEqual(codes[2], 429)

    def test_health_deep_limited_only_for_truthy_values(self):
        with patch.object(app_module, 'RATE_LIMIT_DEEP', 1):
            # deep=01 bukan '1' -> tidak masuk jalur limiter.
            r1 = self.client.get('/health', params={'deep': '01'})
            r2 = self.client.get('/health', params={'deep': '01'})
        self.assertNotEqual(r2.status_code, 429)


if __name__ == '__main__':
    unittest.main()
