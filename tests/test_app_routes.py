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

    def test_billboard_keeps_landscape_banner_and_dedupes(self):
        """Billboard harus memakai banner landscape MENTAH (tanpa resolve
        portrait) dan tidak menampilkan slug yang sama dua kali."""
        populer = {
            "manga": {"title": "Manga", "items": [
                {"slug": "a", "title": "A", "thumbnail": "//x.komiku.org/h-a.jpg?resize=450,235"},
                {"slug": "b", "title": "B", "thumbnail": "//x.komiku.org/h-b.jpg"},
            ]},
            "manhwa": {"title": "Manhwa", "items": [
                {"slug": "a", "title": "A dup", "thumbnail": "//x.komiku.org/h-a2.jpg"},
                {"slug": "c", "title": "C", "thumbnail": ""},
            ]},
        }
        rekomendasi = [{"slug": "d", "title": "D", "thumbnail": "//x.komiku.org/h-d.jpg"}]
        with patch.object(app_module.api, "_get", side_effect=[populer, rekomendasi]) as m:
            res = self.client.get("/api/billboard")
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertEqual([i["slug"] for i in items], ["a", "b", "d"])
        # Cover landscape asli dipertahankan + param resize tidak dibuang.
        self.assertEqual(items[0]["cover"], "https://x.komiku.org/h-a.jpg?resize=450,235")
        # Item tanpa cover valid (c) tidak ikut.
        self.assertNotIn("c", [i["slug"] for i in items])
        calls = [p.args[0] for p in m.call_args_list]
        self.assertEqual(calls, ["/komik-populer", "/rekomendasi"])

    def test_frontend_served_from_disk(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Zomic", res.text)


if __name__ == "__main__":
    unittest.main()
