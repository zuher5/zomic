import base64
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scraper.downloader import (
    DownloadError,
    ImageDownloader,
    InvalidImage,
    OversizedContent,
    UnsupportedUrl,
    sanitize_url,
)
from scraper.storage import FileStorage

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/img.png":
            self._send(PNG_1X1)
        elif self.path == "/text.txt":
            self._send(b"not an image")
        elif self.path == "/big.png":
            self._send(b"x" * 5000)
        else:
            self.send_error(404)

    def _send(self, body):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DownloaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = FileStorage(self.tmpdir)
        self.downloader = ImageDownloader(
            self.storage, allow_private=True, retries=1
        )

    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def test_download_valid_image(self):
        key = self.downloader.download(f"{self.base()}/img.png")
        self.assertTrue(self.storage.exists(key))
        with open(os.path.join(self.tmpdir, key), "rb") as fh:
            self.assertEqual(fh.read(), PNG_1X1)

    def test_rejects_non_image(self):
        with self.assertRaises(InvalidImage):
            self.downloader.download(f"{self.base()}/text.txt")

    def test_404_raises(self):
        with self.assertRaises(DownloadError):
            self.downloader.download(f"{self.base()}/missing.png")

    def test_oversized_content(self):
        downloader = ImageDownloader(
            self.storage, allow_private=True, max_bytes=100, retries=1
        )
        with self.assertRaises(OversizedContent):
            downloader.download(f"{self.base()}/big.png")

    def test_blocks_private_host_by_default(self):
        downloader = ImageDownloader(self.storage, retries=1)
        with self.assertRaises(UnsupportedUrl):
            downloader.download(f"{self.base()}/img.png")

    def test_sanitize_url_rejects_schemes(self):
        with self.assertRaises(UnsupportedUrl):
            sanitize_url("file:///etc/passwd")
        with self.assertRaises(UnsupportedUrl):
            sanitize_url("ftp://example.com/x.png")

    def test_allowed_hosts_restriction(self):
        with self.assertRaises(UnsupportedUrl):
            sanitize_url(f"{self.base()}/img.png", allowed_hosts=["cdn.example.com"])

    def test_download_many(self):
        results = self.downloader.download_many(
            [f"{self.base()}/img.png", f"{self.base()}/missing.png"]
        )
        self.assertTrue(results[f"{self.base()}/img.png"].startswith("images/"))
        self.assertTrue(results[f"{self.base()}/missing.png"].startswith("error:"))


if __name__ == "__main__":
    unittest.main()