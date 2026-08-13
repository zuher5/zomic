import unittest

from scraper.downloader import UnsupportedUrl, detect_image_type, sanitize_url
from backend.api import RateLimiter


class RateLimiterTest(unittest.TestCase):
    def test_allows_up_to_limit(self):
        limiter = RateLimiter(max_requests=3, window=60)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))

    def test_independent_keys(self):
        limiter = RateLimiter(max_requests=1, window=60)
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))


class SsrfProtectionTest(unittest.TestCase):
    def test_blocks_private_and_link_local_hosts(self):
        for host in ["127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.1.1", "localhost", "0.0.0.0"]:
            with self.subTest(host=host):
                with self.assertRaises(UnsupportedUrl):
                    sanitize_url(f"http://{host}/x.png")

    def test_blocks_non_http_schemes(self):
        for url in ["file:///etc/passwd", "ftp://x/a.png", "javascript:alert(1)"]:
            with self.subTest(url=url):
                with self.assertRaises(UnsupportedUrl):
                    sanitize_url(url)

    def test_detect_image_rejects_non_image(self):
        self.assertIsNone(detect_image_type(b"<html>not an image</html>"))
        self.assertIsNotNone(detect_image_type(b"\x89PNG\r\n\x1a\n rest"))


if __name__ == "__main__":
    unittest.main()