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


class ComicApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmpdir, "api.db")
        repo = Repository(cls.db_path)
        scrape_series(KomikCastSource(fetcher=fake_fetcher), repo, SLUG)
        os.environ["ZOMIC_DB"] = cls.db_path
        from backend.api import app

        cls.client = TestClient(app)

    def test_list_comics(self):
        res = self.client.get("/api/comics")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["meta"]["total"], 1)
        self.assertEqual(body["data"][0]["slug"], SLUG)

    def test_list_comics_pagination(self):
        res = self.client.get("/api/comics?page=1&limit=5")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["data"]), 1)

    def test_get_comic(self):
        res = self.client.get("/api/comics/1")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["title"], "Kidnapped The Youngest Daughter of The Sichuan Tang Family")
        self.assertIn("Action", data["genres"])

    def test_comic_chapters(self):
        res = self.client.get("/api/comics/1/chapters")
        self.assertEqual(res.status_code, 200)
        chapters = res.json()["data"]
        self.assertEqual(len(chapters), 3)
        self.assertEqual([c["index"] for c in chapters], [1, 2, 3])

    def test_get_chapter(self):
        res = self.client.get("/api/chapters/1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"]["comic_id"], 1)

    def test_chapter_pages(self):
        res = self.client.get("/api/chapters/1/pages")
        self.assertEqual(res.status_code, 200)
        pages = res.json()["data"]
        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[0]["position"], 1)

    def test_search(self):
        res = self.client.get("/api/search", params={"q": "sichuan"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["meta"]["total"], 1)
        self.assertEqual(body["data"][0]["slug"], SLUG)

    def test_search_no_results(self):
        res = self.client.get("/api/search", params={"q": "zzz-no-such-comic"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"], [])

    def test_search_requires_query(self):
        self.assertEqual(self.client.get("/api/search").status_code, 422)
        self.assertEqual(self.client.get("/api/search", params={"q": ""}).status_code, 422)

    def test_search_pagination(self):
        res = self.client.get("/api/search", params={"q": "sichuan", "page": 2, "limit": 5})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"], [])

    def test_not_found(self):
        self.assertEqual(self.client.get("/api/comics/999").status_code, 404)
        self.assertEqual(self.client.get("/api/chapters/999").status_code, 404)
        self.assertEqual(self.client.get("/api/comics/999/chapters").status_code, 404)
        self.assertEqual(self.client.get("/api/chapters/999/pages").status_code, 404)

    def test_invalid_input(self):
        self.assertEqual(self.client.get("/api/comics?limit=0").status_code, 422)
        self.assertEqual(self.client.get("/api/comics?page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/comics?limit=1000").status_code, 422)


if __name__ == "__main__":
    unittest.main()