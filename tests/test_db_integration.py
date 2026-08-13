import json
import os
import tempfile
import unittest

from urllib.parse import urlparse

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


class DatabaseIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.source = KomikCastSource(fetcher=fake_fetcher)

    def test_scrape_is_idempotent(self):
        repo = Repository(self.db_path)
        scrape_series(self.source, repo, SLUG)
        first = repo.counts()
        scrape_series(self.source, repo, SLUG)
        second = repo.counts()

        self.assertGreater(first["comic"], 0)
        self.assertGreater(first["chapter"], 0)
        self.assertGreater(first["page"], 0)
        self.assertEqual(first, second)
        self.assertEqual(first["comic"], 1)
        self.assertEqual(first["chapter"], 3)
        self.assertEqual(first["page"], 9)

    def test_scrape_metadata(self):
        repo = Repository(self.db_path)
        scrape_series(self.source, repo, SLUG, with_pages=False)
        comic = repo.conn.execute(
            "SELECT title, author, status FROM comic WHERE slug = ?", (SLUG,)
        ).fetchone()
        self.assertEqual(comic["title"], "Kidnapped The Youngest Daughter of The Sichuan Tang Family")
        self.assertEqual(comic["status"], "ongoing")


if __name__ == "__main__":
    unittest.main()