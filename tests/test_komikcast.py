import json
import os
import unittest

from urllib.parse import urlparse

from scraper.http import HttpError
from scraper.sources.komikcast import KomikCastSource

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

SLUG = "kidnapped-the-youngest-daughter-of-the-sichuan-tang-family"


def load(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


def fake_fetcher(url, *args, **kwargs):
    path = urlparse(url).path.strip("/")
    if path == f"series/{SLUG}":
        return load("series_detail.json")
    if path in (f"series/{SLUG}/chapters/1", f"series/{SLUG}/chapters/413629"):
        return load("chapter_pages.json")
    if path == f"series/{SLUG}/chapters":
        return load("chapters.json")
    if path == "series":
        return {
            "status": 200,
            "data": [load("series_detail.json")["data"]],
            "meta": {"total": 1, "page": 1, "lastPage": 1},
        }
    raise HttpError(f"not found: {url}")


class KomikCastSourceTest(unittest.TestCase):
    def setUp(self):
        self.source = KomikCastSource(fetcher=fake_fetcher)

    def test_get_comic(self):
        comic = self.source.get_comic(SLUG)
        self.assertEqual(comic.source, "komikcast")
        self.assertEqual(comic.external_id, "10288")
        self.assertEqual(comic.slug, SLUG)
        self.assertEqual(
            comic.title, "Kidnapped The Youngest Daughter of The Sichuan Tang Family"
        )
        self.assertEqual(comic.author, "SON,오리너구리")
        self.assertEqual(comic.status, "ongoing")
        self.assertIn("Action", comic.genres)
        self.assertTrue(comic.cover_url.startswith("https://minio."))

    def test_search(self):
        results = self.source.search("sichuan")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].slug, SLUG)

    def test_get_chapters_lists_all(self):
        chapters = self.source.get_chapters(SLUG)
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[0].index, 2)
        self.assertEqual(chapters[0].external_id, "413630")

    def test_get_pages_ordered(self):
        pages = self.source.get_pages(SLUG, "1")
        images = load("chapter_pages.json")["data"]["data"]["images"]
        self.assertEqual(len(pages), len(images))
        self.assertEqual([p.position for p in pages], [1, 2, 3])
        self.assertEqual([p.url for p in pages], images)

    def test_get_pages_by_id(self):
        pages = self.source.get_pages(SLUG, 413629)
        self.assertEqual(len(pages), 3)

    def test_404_raises(self):
        with self.assertRaises(HttpError):
            self.source.get_comic("does-not-exist")


if __name__ == "__main__":
    unittest.main()