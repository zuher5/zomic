import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from app import app, cache


class ApiRoutesTest(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.client = TestClient(app)

    def test_img_proxy_blocks_foreign_and_internal_hosts(self):
        for url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8000/health",
            "https://evil.example.com/x.png",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get("/api/img", params={"url": url}).status_code, 403)

    def test_img_proxy_rejects_non_http_scheme(self):
        self.assertEqual(self.client.get("/api/img", params={"url": "file:///etc/passwd"}).status_code, 400)

    def test_img_host_allowlist_matches_subdomains_only(self):
        allowed = app_module._img_host_allowed
        self.assertTrue(allowed("img.komiku.org"))
        self.assertTrue(allowed("komiku.org"))
        self.assertTrue(allowed("thumbnail.komiku.org:443"))
        self.assertFalse(allowed("komiku.org.evil.com"))
        self.assertFalse(allowed("notkomiku.org"))
        self.assertFalse(allowed(None))

    def test_catalog_validates_params(self):
        self.assertEqual(self.client.get("/api/catalog?page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/catalog?page=999").status_code, 422)
        self.assertEqual(self.client.get("/api/catalog?type=bogus").status_code, 422)

    def test_search_requires_query(self):
        self.assertEqual(self.client.get("/api/search?q=").status_code, 422)

    def test_catalog_returns_pagination_envelope(self):
        payload = {
            "items": [{"slug": "a", "title": "A", "cover": "", "type": "Manga",
                       "genre": "Aksi", "status": "Ongoing", "chapter": ""}],
            "page": 2, "per_page": 50, "total": 7615, "total_pages": 153,
            "has_next": True, "filters": {"type": "", "letter": ""},
        }
        with patch.object(app_module.web, "catalog", return_value=payload) as m:
            res = self.client.get("/api/catalog?page=2&type=manga&letter=b")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["total"], 7615)
        m.assert_called_once_with(2, ctype="manga", letter="b")

    def test_responses_are_cached(self):
        with patch.object(app_module.web, "genres", return_value=[{"slug": "action", "name": "Action"}]) as m:
            self.client.get("/api/genres")
            self.client.get("/api/genres")
        m.assert_called_once()

    def test_genre_not_found_returns_404(self):
        empty = {"items": [], "page": 1, "per_page": 10, "genre": "nope", "has_next": False}
        with patch.object(app_module.web, "by_genre", return_value=empty):
            self.assertEqual(self.client.get("/api/genre/nope").status_code, 404)

    def test_upstream_failure_becomes_502(self):
        import requests

        with patch.object(app_module.web, "catalog", side_effect=requests.ConnectionError("boom")):
            self.assertEqual(self.client.get("/api/catalog?page=1").status_code, 502)

    def test_chapter_endpoint_returns_array(self):
        with patch.object(app_module.api, "chapter", return_value=["https://img.komiku.org/1.webp"]):
            res = self.client.get("/api/chapter/some-slug/12")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)

    def test_frontend_served_from_disk(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Zomic", res.text)

    def test_to_en_ago_converts_upstream_update_time(self):
        f = app_module._to_en_ago
        self.assertEqual(f("24 menit lalu"), "24 min ago")
        self.assertEqual(f("1 menit lalu"), "1 min ago")
        self.assertEqual(f("51 detik lalu"), "51 sec ago")
        self.assertEqual(f("1 jam lalu"), "1 hour ago")
        self.assertEqual(f("3 jam lalu"), "3 hours ago")
        self.assertEqual(f("1 hari lalu"), "1 day ago")
        self.assertEqual(f("2 hari lalu"), "2 days ago")
        self.assertEqual(f("3 bulan lalu"), "3 months ago")
        self.assertEqual(f("1 tahun lalu"), "1 year ago")
        # Tak dikenali -> apa adanya (kiryuu EN, kosong, '-')
        self.assertEqual(f("10 months ago"), "10 months ago")
        self.assertEqual(f(""), "")
        self.assertEqual(f("-"), "-")


if __name__ == "__main__":
    unittest.main()
