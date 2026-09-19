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
        os.environ.pop('IMAGE_PREFER_AVIF', None)
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
        self.assertEqual(c.get('/api/img', params={'url': 'https://uqni.net.evil.com/x.png'}).status_code, 403)
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

    def test_uqni_cdn_host_is_allowed(self):
        with self._fetch(WEBP_SRC):
            r = self.client.get('/api/img', params={'url': 'https://cdn.uqni.net/users/7/2026/08/000-899706.webp'})
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

    def test_avif_when_accepted_but_default_optin_off(self):
        # IMAGE_PREFER_AVIF default 0 → format=auto memakai WebP meski klien
        # menerima AVIF (encode AVIF Pillow sangat lambat).
        with self._fetch(PNG_SRC):
            r = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                    'w': 400, 'format': 'auto', 'q': 78},
                                headers={'Accept': 'image/avif,image/webp,image/*'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['content-type'], 'image/webp')

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

    def test_oversized_source_rejected_before_load(self):
        # Dimensi di header raksasa (> 25 MP) harus ditolak SEBELUM decompress:
        # Image.load() tidak boleh dipanggil, supaya decompression bomb tidak
        # sempat menghabiskan memori.
        class FakeImg:
            size = (100_000, 100_000)
            load_called = False

            def load(self):
                FakeImg.load_called = True

        with self._fetch(b'unused'), \
             patch.object(self.app.Image, 'open', return_value=FakeImg()):
            r = self.client.get('/api/img', params={'url': 'https://img.komiku.org/cover/x.png',
                                                    'w': 400, 'format': 'webp'})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()['detail'], 'image too large')
        self.assertFalse(FakeImg.load_called)


class FormatAutoVaryTest(unittest.TestCase):
    """format=auto memilih output dari header Accept → wajib Vary: Accept
    di semua jalur response, supaya CDN tidak melayani AVIF ke browser yang
    hanya mendukung JPEG/WebP."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ['IMAGE_CACHE_DIR'] = cls.tmp
        os.environ.pop('IMAGE_PREFER_AVIF', None)
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

    def _get(self, accept, **extra):
        params = {'url': 'https://img.komiku.org/cover/x.png', 'w': 400,
                  'format': 'auto', 'q': 78, **extra}
        return self.client.get('/api/img', params=params,
                               headers={'Accept': accept})

    def test_avif_accept_gets_webp_by_default(self):
        # IMAGE_PREFER_AVIF default 0 → auto = WebP (encode cepat), bukan AVIF.
        with self._fetch(PNG_SRC):
            r = self._get('image/avif,image/webp,image/*')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers['content-type'], 'image/webp')
        self.assertIn('Accept', r.headers.get('vary', ''))

    def test_webp_accept_gets_webp_and_vary(self):
        with self._fetch(PNG_SRC):
            r = self._get('image/webp,image/*')
        self.assertEqual(r.headers['content-type'], 'image/webp')
        self.assertIn('Accept', r.headers.get('vary', ''))

    def test_jpeg_only_accept_gets_jpeg_and_vary(self):
        with self._fetch(PNG_SRC):
            r = self._get('image/jpeg,image/*')
        self.assertEqual(r.headers['content-type'], 'image/jpeg')
        self.assertIn('Accept', r.headers.get('vary', ''))

    def test_vary_present_on_cache_hit(self):
        with self._fetch(PNG_SRC):
            r1 = self._get('image/webp,image/*')
            r2 = self._get('image/webp,image/*')
        self.assertEqual(r1.headers['x-image-cache'], 'MISS')
        self.assertEqual(r2.headers['x-image-cache'], 'HIT')
        self.assertIn('Accept', r2.headers.get('vary', ''))
        self.assertIn('immutable', r2.headers['cache-control'])

    def test_vary_present_on_processing_fallback(self):
        with patch.object(self.app, '_process_image', side_effect=ValueError('boom')):
            with self._fetch(PNG_SRC):
                r = self._get('image/webp,image/*')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, PNG_SRC)
        self.assertIn('Accept', r.headers.get('vary', ''))

    def test_explicit_format_has_no_vary_accept(self):
        with self._fetch(PNG_SRC):
            r = self.client.get('/api/img',
                                params={'url': 'https://img.komiku.org/cover/x.png',
                                        'w': 400, 'format': 'webp', 'q': 78})
        self.assertEqual(r.headers['content-type'], 'image/webp')
        self.assertNotIn('Accept', r.headers.get('vary', ''))

    def test_legacy_passthrough_has_no_vary_accept(self):
        with self._fetch(WEBP_SRC):
            r = self.client.get('/api/img',
                                params={'url': 'https://img.komiku.org/cover/x.webp'})
        self.assertNotIn('Accept', r.headers.get('vary', ''))


class FormatAutoAvifOptInTest(unittest.TestCase):
    """IMAGE_PREFER_AVIF=1 → format=auto memilih AVIF bila Pillow mendukung."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ['IMAGE_CACHE_DIR'] = cls.tmp
        os.environ['IMAGE_PREFER_AVIF'] = '1'
        import app as app_module
        importlib.reload(app_module)
        cls.app = app_module
        cls.client = TestClient(app_module.app)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop('IMAGE_PREFER_AVIF', None)

    def setUp(self):
        self.app.cache.clear()
        for f in os.listdir(self.app.IMAGE_CACHE_DIR):
            try:
                os.remove(os.path.join(self.app.IMAGE_CACHE_DIR, f))
            except OSError:
                pass

    def test_auto_avif_when_optin_and_supported(self):
        def _fetch(data):
            ctype = self.app._ctype_from_bytes(data)
            return patch.object(self.app, '_img_fetch', return_value=(data, ctype))
        with _fetch(PNG_SRC):
            r = self.client.get('/api/img',
                                params={'url': 'https://img.komiku.org/cover/x.png',
                                        'w': 400, 'format': 'auto', 'q': 78},
                                headers={'Accept': 'image/avif,image/webp,image/*'})
        self.assertEqual(r.status_code, 200)
        expected = 'image/avif' if self.app._avif_supported() else 'image/webp'
        self.assertEqual(r.headers['content-type'], expected)

    def test_explicit_avif_format_always_respected(self):
        def _fetch(data):
            ctype = self.app._ctype_from_bytes(data)
            return patch.object(self.app, '_img_fetch', return_value=(data, ctype))
        with _fetch(PNG_SRC):
            r = self.client.get('/api/img',
                                params={'url': 'https://img.komiku.org/cover/x.png',
                                        'w': 400, 'format': 'avif', 'q': 80})
        self.assertEqual(r.status_code, 200)
        expected = 'image/avif' if self.app._avif_supported() else 'image/webp'
        self.assertEqual(r.headers['content-type'], expected)


class FormatAutoDefaultWebpTest(unittest.TestCase):
    """format=auto default (IMAGE_PREFER_AVIF off): WebP untuk klien webp,
    JPEG untuk klien jpeg-only. AVIF TIDAK dipilih di path auto."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ['IMAGE_CACHE_DIR'] = cls.tmp
        os.environ.pop('IMAGE_PREFER_AVIF', None)
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

    def test_pick_format_auto_prefers_webp_over_avif(self):
        pick = self.app._pick_format
        self.assertEqual(pick('auto', 'image/avif,image/webp,image/*'), 'WEBP')
        self.assertEqual(pick('auto', 'image/webp,*/*'), 'WEBP')
        self.assertEqual(pick('auto', 'image/jpeg,*/*'), 'JPEG')
        self.assertEqual(pick('webp', 'image/avif,*/*'), 'WEBP')
        self.assertEqual(pick('avif', 'image/webp,*/*'), 'AVIF' if self.app._avif_supported() else 'WEBP')
        self.assertIsNone(pick('original', '*/*'))


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

    def test_health_default_does_not_scrape_upstream(self):
        with patch.object(self.app, 'api') as api_mock, \
             patch.object(self.app, 'web') as web_mock:
            r = self.client.get('/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'ok')
        api_mock.latest.assert_not_called()
        web_mock.catalog.assert_not_called()

    def test_health_deep_mode_still_diagnoses_upstream(self):
        with patch.object(self.app.api, 'latest', return_value=[{'slug': 'a'}]), \
             patch.object(self.app.web, 'catalog', return_value={'total': 7615}):
            r = self.client.get('/health?deep=1')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['comics_found'], 1)
        self.assertEqual(body['catalog_total'], 7615)


class RedirectSsrfTest(unittest.TestCase):
    """_img_open mengikuti redirect MANUAL dan memvalidasi tiap hop: host
    allowlist yang membalas 302 ke IP internal / host di luar allowlist tidak
    boleh dilewati (SSRF via Location header)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ['IMAGE_CACHE_DIR'] = cls.tmp
        import app as app_module
        importlib.reload(app_module)
        cls.app = app_module

    def setUp(self):
        self.app.cache.clear()

    class _Resp:
        def __init__(self, status, headers=None):
            self.status_code = status
            self.headers = headers or {}
            self.closed = False

        def close(self):
            self.closed = True

    def test_redirect_to_internal_host_is_blocked(self):
        seq = [self._Resp(302, {'Location': 'http://169.254.169.254/latest/meta-data/'})]
        with patch.object(self.app, 'retry_get', side_effect=lambda *a, **k: seq.pop(0)):
            with self.assertRaises(self.app.HTTPException) as ctx:
                self.app._img_open(object(), 'https://img.komiku.org/a.png')
        self.assertEqual(ctx.exception.status_code, 502)

    def test_redirect_to_non_allowlisted_host_is_blocked(self):
        seq = [self._Resp(302, {'Location': 'https://evil.example.com/x.png'})]
        with patch.object(self.app, 'retry_get', side_effect=lambda *a, **k: seq.pop(0)):
            with self.assertRaises(self.app.HTTPException):
                self.app._img_open(object(), 'https://img.komiku.org/a.png')

    def test_redirect_to_allowed_host_is_followed(self):
        seq = [
            self._Resp(302, {'Location': 'https://img.komiku.org/real.png'}),
            self._Resp(200),
        ]
        calls = []

        def fake_get(_session, url, **kwargs):
            calls.append(url)
            return seq.pop(0)

        with patch.object(self.app, 'retry_get', side_effect=fake_get):
            resp = self.app._img_open(object(), 'https://img.komiku.org/a.png')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(calls, ['https://img.komiku.org/a.png', 'https://img.komiku.org/real.png'])

    def test_no_redirect_disables_auto_follow(self):
        seen = {}

        def fake_get(_session, url, **kwargs):
            seen.update(kwargs)
            return self._Resp(200)

        with patch.object(self.app, 'retry_get', side_effect=fake_get):
            self.app._img_open(object(), 'https://img.komiku.org/a.png')
        self.assertIs(seen.get('allow_redirects'), False)

    def test_redirect_loop_is_capped(self):
        def fake_get(_session, url, **kwargs):
            return self._Resp(302, {'Location': 'https://img.komiku.org/loop.png'})

        with patch.object(self.app, 'retry_get', side_effect=fake_get):
            with self.assertRaises(self.app.HTTPException):
                self.app._img_open(object(), 'https://img.komiku.org/a.png')


class SecurityHeaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as app_module
        importlib.reload(app_module)
        cls.client = TestClient(app_module.app)

    def test_security_headers_present(self):
        r = self.client.get('/health')
        self.assertEqual(r.headers.get('x-content-type-options'), 'nosniff')
        self.assertEqual(r.headers.get('x-frame-options'), 'DENY')
        self.assertIn('content-security-policy', r.headers)
        self.assertIn('frame-ancestors', r.headers['content-security-policy'])

    def test_docs_disabled_by_default(self):
        self.assertEqual(self.client.get('/docs').status_code, 404)
        self.assertEqual(self.client.get('/openapi.json').status_code, 404)


if __name__ == "__main__":
    unittest.main()