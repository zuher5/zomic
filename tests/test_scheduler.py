import json
import os
import tempfile
import unittest

from urllib.parse import urlparse

from scraper.http import HttpError
from scraper.incremental import sync_series
from scraper.queue import JobQueue
from scraper.repository import Repository
from scraper.scheduler import run_scheduler_once
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


class IncrementalAndSchedulerTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.repo = Repository(self.db_path)
        self.queue = JobQueue(self.db_path)
        self.source = KomikCastSource(fetcher=fake_fetcher)

    def test_existing_chapters_are_skipped(self):
        stats = sync_series(self.source, self.repo, self.queue, SLUG)
        self.assertEqual(stats["new_chapters"], 3)
        self.assertEqual(stats["existing_chapters"], 0)
        self.assertEqual(stats["queued_pages"], 3)

        stats = sync_series(self.source, self.repo, self.queue, SLUG)
        self.assertEqual(stats["new_chapters"], 0)
        self.assertEqual(stats["existing_chapters"], 3)
        self.assertEqual(stats["queued_pages"], 0)
        self.assertEqual(self.repo.counts()["chapter"], 3)

    def test_sync_enqueues_pages_and_download_jobs(self):
        sync_series(self.source, self.repo, self.queue, SLUG)
        counts = self.queue.counts()
        self.assertEqual(counts["queued"], 4)
        self.assertEqual(len(self.repo.get_pending_pages()), 0)

    def test_scheduler_reports_no_new_chapters_on_second_run(self):
        sync_series(self.source, self.repo, self.queue, SLUG)
        report = run_scheduler_once(self.db_path, with_pages=True, source_factory=self._factory)
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["slug"], SLUG)
        self.assertEqual(report[0]["stats"]["new_chapters"], 0)

    def _factory(self, name):
        return self.source


if __name__ == "__main__":
    unittest.main()