import base64
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.testclient import TestClient

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/img.png":
            self.send_response(200)
            self.send_header("Content-Length", str(len(PNG_1X1)))
            self.end_headers()
            self.wfile.write(PNG_1X1)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


class ImageProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.environ["ZOMIC_DB"] = os.path.join(self.tmpdir, "proxy.db")
        os.environ["IMAGE_CDN_HOSTS"] = "127.0.0.1"
        os.environ["IMAGE_ALLOW_PRIVATE"] = "1"
        from backend.api import app

        self.client = TestClient(app)
        self.base = f"http://127.0.0.1:{self.port}"

    def test_proxy_returns_image(self):
        res = self.client.get("/api/images", params={"url": f"{self.base}/img.png"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "image/png")
        self.assertEqual(res.content, PNG_1X1)

    def test_proxy_rejects_unknown_host(self):
        res = self.client.get("/api/images", params={"url": "http://evil.example.com/x.png"})
        self.assertEqual(res.status_code, 400)

    def test_proxy_rejects_bad_scheme(self):
        res = self.client.get("/api/images", params={"url": "file:///etc/passwd"})
        self.assertEqual(res.status_code, 400)

    def test_proxy_requires_url(self):
        res = self.client.get("/api/images")
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()