import importlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image


def _png(w=600, h=900, color=(200, 60, 60)):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), color).save(buf, 'PNG')
    return buf.getvalue()


def _webp(w=600, h=900, color=(30, 90, 200)):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), color).save(buf, 'WEBP')
    return buf.getvalue()


PNG_SRC = _png()
WEBP_SRC = _webp()


class ImageProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ['IMAGE_CACHE_DIR'] = cls.tmp
        import app as app_module
        importlib.reload(app_module)
        cls.app = app_module
        cls.client = TestClient(app_module.app)

    def setUp(self):
        self.app.cache.clear()
        for f in os.listdir(self.app.IMAGE_CACHE_DIR):
            try:
                os.remove(os.path.join(self.app.IMAGE_CACHE_DIR, f))
            except OSError:
                pass

    def _fetch(self, data):
        ctype = self.app._ctype_from_bytes(data)
        return patch.object(self.app, '_img_fetch', return_value=(data, ctype))

    def test_validation_rejects_bad_input(self):
        c = self.client
        self.assertEqual(c.get('/api/img', params={'url': 'file:///etc/passwd'}).status_code, 400)
        self.assertEqual(c.get('/api/img', params={'url': 'http://localhost:8000/health'}).status_code, 403)
        self.assertEqual(c.get('/api/img', params={'url': 'http://127.0.0.1/x.png'}).status_code, 403)
        self.assertEqual(c.get('/api/img', params={'url': 'http://169.254.169.254/x.png'}).status_code, 403)
        self.assertEqual(c.get('/api/img', params={'url': 'https://komiku.org.evil.com/x.png'}).status_code, 403)
        self.assertEqual(c.get('/api/img', params={'url': 'http://img.komiku.org/a.png', 'w': 50}).status_code, 422)
        self.assertEqual(c.get('/api/img', params={'url': 'http://img.komiku.org/a.png', 'w': 900}).status_code, 422)
        self.assertEqual(c.get('/api/img', params={'url': 'http://img.komiku.org/a.png', 'q': 10}).status_code, 422)
        self.assertEqual(c.get('/api/img', params={'url': 'http://img.komiku.org/a.png', 'format': 'bmp'}).status_code, 422)

    def test_legacy_passthrough_no_resize(self):
        with self._fetch(WEBP_SRC):
            r = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.webp'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, WEBP_SRC)
        self.assertEqual(r.headers['content-type'], 'image/webp')
        self.assertIn('max-age=86400', r.headers['cache-control'])
        self.assertIn('x-image-cache', r.headers)

    def test_thumbnail_to_host_is_allowed(self):
        with self._fetch(WEBP_SRC):
            r = self.client.get('/api/img', params={'url': 'https://thumbnail.komiku.to/new/cover.webp'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['content-type'], 'image/webp')

    def test_resize_and_webp_format(self):
        with self._fetch(PNG_SRC):
            r = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                    'w': 400, 'format': 'webp', 'q': 78})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['content-type'], 'image/webp')
        img = Image.open(io.BytesIO(r.content))
        self.assertLessEqual(img.width, 400)
        self.assertAlmostEqual(img.height / img.width, 1.5, delta=0.02)

    def test_avif_when_accepted(self):
        with self._fetch(PNG_SRC):
            r = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                    'w': 400, 'format': 'auto', 'q': 78},
                                headers={'Accept': 'image/avif,image/webp,image/*'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.headers['content-type'], ('image/avif', 'image/webp'))

    def test_no_upscale(self):
        with self._fetch(_png(150, 225)):
            r = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                    'w': 400, 'format': 'webp'})
        img = Image.open(io.BytesIO(r.content))
        self.assertEqual(img.width, 150)

    def test_cache_hit_after_first_request(self):
        params = {'url': 'https://img.komiku.org/cover/x.png', 'w': 400, 'format': 'webp', 'q': 78}
        with self._fetch(PNG_SRC):
            r1 = self.client.get('/api/img', params=params)
            r2 = self.client.get('/api/img', params=params)
        self.assertEqual(r1.headers['x-image-cache'], 'MISS')
        self.assertEqual(r2.headers['x-image-cache'], 'HIT')
        self.assertEqual(r1.content, r2.content)
        self.assertIn('immutable', r2.headers['cache-control'])

    def test_cache_key_depends_on_params(self):
        with self._fetch(PNG_SRC):
            a = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                    'w': 400, 'format': 'webp', 'q': 78})
            b = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                    'w': 240, 'format': 'webp', 'q': 78})
        self.assertEqual(a.headers['x-image-cache'], 'MISS')
        self.assertEqual(b.headers['x-image-cache'], 'MISS')

    def test_fallback_when_processing_fails(self):
        with patch.object(self.app, '_process_image', side_effect=ValueError('boom')):
            with self._fetch(PNG_SRC):
                r = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                        'w': 400, 'format': 'webp'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, PNG_SRC)
        self.assertIn('max-age=86400', r.headers['cache-control'])

    def test_invalid_source_image_rejected(self):
        with self._fetch(b'<html>not an image</html>'):
            r = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                    'w': 400, 'format': 'webp'})
        self.assertEqual(r.status_code, 502)


class HealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ['IMAGE_CACHE_DIR'] = cls.tmp
        import app as app_module
        importlib.reload(app_module)
        cls.app = app_module
        cls.client = TestClient(app_module.app)

    def test_health_returns_ok_envelope(self):
        r = self.client.get('/health')
        self.assertEqual(r.status_code, 200)
        self.assertIn('status', r.json())


if __name__ == "__main__":
    unittest.main()