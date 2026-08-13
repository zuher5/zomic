import base64
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from scraper.queue import JobQueue
from scraper.repository import Repository
from scraper.sources.komikcast import KomikCastSource
from scraper.worker import Worker

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
SLUG = "kidnapped-the-youngest-daughter-of-the-sichuan-tang-family"


class ImageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/img/") and not self.path.endswith("broken.png"):
            self.send_response(200)
            self.send_header("Content-Length", str(len(PNG_1X1)))
            self.end_headers()
            self.wfile.write(PNG_1X1)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


class WorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ImageHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "worker.db")
        self.storage_root = os.path.join(self.tmpdir, "images")
        self.server_url = f"http://127.0.0.1:{self.port}"
        self.worker = Worker(
            self.db_path,
            storage_root=self.storage_root,
            source_factory=lambda name: KomikCastSource(fetcher=self.fake_fetcher),
            allow_private=True,
        )

    def fake_fetcher(self, url, *args, **kwargs):
        parts = urlparse(url).path.strip("/").split("/")
        if parts == ["series", SLUG]:
            with open(
                os.path.join(os.path.dirname(__file__), "fixtures", "series_detail.json")
            ) as fh:
                return json.load(fh)
        if parts[:2] == ["series", SLUG] and parts[2] == "chapters" and len(parts) == 4:
            ref = parts[3]
            images = [
                f"{self.server_url}/img/{ref}-1.png",
                f"{self.server_url}/img/{ref}-2.png",
                f"{self.server_url}/img/{ref}-3.png",
            ]
            if ref == "3":
                images.append(f"{self.server_url}/img/3-broken.png")
            return {"data": {"data": {"images": images}}}
        if parts[:2] == ["series", SLUG] and parts[2] == "chapters" and len(parts) == 3:
            with open(
                os.path.join(os.path.dirname(__file__), "fixtures", "chapters.json")
            ) as fh:
                return json.load(fh)
        raise AssertionError(f"unexpected url: {url}")

    def test_scrape_and_download_flow(self):
        self.worker.queue.enqueue_scrape_comic(SLUG)
        processed = self.worker.drain()
        self.assertGreater(processed, 0)
        self.assertEqual(self.worker.queue.counts()["failed"], 0)

        repo = Repository(self.db_path)
        self.assertEqual(repo.counts()["comic"], 1)
        self.assertEqual(repo.counts()["chapter"], 3)
        self.assertEqual(repo.counts()["page"], 10)
        self.assertEqual(len(repo.get_pending_pages()), 10)

        self.worker.queue.enqueue_download_images()
        self.worker.drain()
        pending = repo.get_pending_pages()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["url"], f"{self.server_url}/img/3-broken.png")

        downloaded = repo.conn.execute(
            "SELECT storage_key FROM page WHERE downloaded = 1"
        ).fetchall()
        self.assertEqual(len(downloaded), 9)
        for row in downloaded:
            self.assertTrue(os.path.exists(os.path.join(self.storage_root, row["storage_key"])))

    def test_retry_failed_job(self):
        self.worker.queue.enqueue_scrape_comic("broken-slug")
        self.worker.drain()
        counts = self.worker.queue.counts()
        self.assertEqual(counts["failed"], 1)
        retried = self.worker.queue.retry_failed()
        self.assertEqual(len(retried), 1)


if __name__ == "__main__":
    unittest.main()