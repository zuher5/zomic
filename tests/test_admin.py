import json
import os
import tempfile
import unittest

from urllib.parse import urlparse

from fastapi.testclient import TestClient

from scraper.http import HttpError
from scraper.repository import Repository
from scraper.service import scrape_series
from scraper.sources.komikcast import KomikCastSource

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SLUG = "kidnapped-the-youngest-daughter-of-the-sichuan-tang-family"


def load(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def fake_fetcher(url, *args, **kwargs):
    parts = urlparse(url).path.strip("/").split("/")
    if parts == ["series", SLUG]:
        return load("series_detail.json")
    if parts[:2] == ["series", SLUG] and parts[2] == "chapters" and len(parts) == 4:
        return load("chapter_pages.json")
    if parts[:2] == ["series", SLUG] and parts[2] == "chapters" and len(parts) == 3:
        return load("chapters.json")
    raise HttpError(f"not found: {url}")


class AdminApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmpdir, "admin.db")
        repo = Repository(cls.db_path)
        scrape_series(KomikCastSource(fetcher=fake_fetcher), repo, SLUG)
        cls.repo = repo

    def setUp(self):
        os.environ["ZOMIC_DB"] = self.db_path
        os.environ["ZOMIC_ADMIN_TOKEN"] = "test-token"
        from backend.api import app

        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-token"}

    def test_admin_requires_token(self):
        self.assertEqual(self.client.get("/api/admin/sources").status_code, 401)
        self.assertEqual(
            self.client.get("/api/admin/sources", headers={"Authorization": "Bearer wrong"}).status_code,
            401,
        )

    def test_admin_unconfigured(self):
        os.environ.pop("ZOMIC_ADMIN_TOKEN")
        from backend.api import app

        res = self.client.get("/api/admin/sources")
        self.assertEqual(res.status_code, 503)

    def test_list_sources(self):
        res = self.client.get("/api/admin/sources", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        sources = res.json()["data"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["name"], "komikcast")
        self.assertEqual(sources[0]["enabled"], 1)

    def test_disable_enable_source(self):
        res = self.client.post("/api/admin/sources/1/disable", headers=self.headers)
        self.assertEqual(res.json()["data"]["enabled"], 0)
        res = self.client.post("/api/admin/sources/1/enable", headers=self.headers)
        self.assertEqual(res.json()["data"]["enabled"], 1)

    def test_job_dashboard(self):
        res = self.client.get("/api/admin/jobs", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("queued", body["counts"])
        self.assertIsInstance(body["data"], list)

    def test_manual_scrape(self):
        res = self.client.post(
            "/api/admin/scrape",
            params={"slug": SLUG, "action": "scrape_comic"},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["action"], "scrape_comic")

    def test_scrape_invalid_action(self):
        res = self.client.post(
            "/api/admin/scrape",
            params={"slug": SLUG, "action": "nope"},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 422)

    def test_retry_failed(self):
        res = self.client.post(
            "/api/admin/scrape",
            params={"slug": SLUG, "action": "retry_failed"},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("retried", res.json()["data"])


if __name__ == "__main__":
    unittest.main()