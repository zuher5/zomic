import unittest
from unittest.mock import MagicMock, patch

import requests

import app as app_module


def card(slug, cover):
    return {'title': slug, 'slug': slug, 'cover': cover, 'type': 'Manga',
            'genre': '', 'status': '', 'chapter': '', 'readers': ''}


BANNER = 'https://thumbnail.komiku.to/manga_img_horizontal-abc/cover.webp'
BANNER_RESIZE = 'https://thumbnail.komiku.to/new/cover.webp?resize=240,150'
PORTRAIT = 'https://thumbnail.komiku.to/manga_thumbnail-abc/cover.webp'
PLAIN = 'https://img.komiku.org/cover/entah.webp'


class NeedsPortraitResolutionTest(unittest.TestCase):
    def test_manga_thumbnail_is_already_portrait(self):
        self.assertFalse(app_module.KomikuAPI._needs_portrait_resolution(
            card('a', PORTRAIT)))

    def test_landscape_markers_trigger_resolution(self):
        self.assertTrue(app_module.KomikuAPI._needs_portrait_resolution(
            card('a', BANNER)))
        self.assertTrue(app_module.KomikuAPI._needs_portrait_resolution(
            card('a', BANNER_RESIZE)))
        self.assertTrue(app_module.KomikuAPI._needs_portrait_resolution(
            card('a', 'https://x.komiku.org/img?resize=450,235')))

    def test_unknown_cover_is_also_resolved(self):
        # Pola non-portrait upstream tidak bisa didaftar lewat marker saja
        # (img/upload, new/img, varian resize lain) — semua yang bukan
        # manga_thumbnail harus dicoba resolve.
        self.assertTrue(app_module.KomikuAPI._needs_portrait_resolution(
            card('a', PLAIN)))
        self.assertTrue(app_module.KomikuAPI._needs_portrait_resolution(
            card('a', 'https://thumbnail.komiku.to/img/upload/x/img_1.png?resize=240,280')))

    def test_empty_cover_or_slug_is_not_resolved(self):
        self.assertFalse(app_module.KomikuAPI._needs_portrait_resolution(
            card('a', '')))
        self.assertFalse(app_module.KomikuAPI._needs_portrait_resolution(
            {'slug': '', 'cover': BANNER}))


class ResolvePortraitTest(unittest.TestCase):
    def setUp(self):
        app_module.cache.clear()

    def test_manga_thumbnail_does_not_call_portrait_cover(self):
        with patch.object(app_module.api, 'portrait_cover_api') as m1, \
             patch.object(app_module.web, 'portrait_cover') as m2:
            out = app_module.api._resolve_portrait([card('a', PORTRAIT)])
        m1.assert_not_called()
        m2.assert_not_called()
        self.assertEqual(out[0]['cover'], PORTRAIT)

    def test_landscape_cover_calls_resolver(self):
        with patch.object(app_module.api, 'portrait_cover_api', return_value=PORTRAIT) as m:
            out = app_module.api._resolve_portrait([card('a', BANNER)])
        m.assert_called_once_with('a')
        self.assertEqual(out[0]['cover'], PORTRAIT)

    def test_api_failure_falls_back_to_scraper(self):
        with patch.object(app_module.api, 'portrait_cover_api',
                          side_effect=requests.ConnectionError('boom')), \
             patch.object(app_module.web, 'portrait_cover', return_value=PORTRAIT) as m:
            out = app_module.api._resolve_portrait([card('a', BANNER)])
        m.assert_called_once_with('a')
        self.assertEqual(out[0]['cover'], PORTRAIT)

    def test_resolver_failure_keeps_upstream_cover(self):
        with patch.object(app_module.api, 'portrait_cover_api',
                          side_effect=requests.ConnectionError('boom')), \
             patch.object(app_module.web, 'portrait_cover',
                          side_effect=requests.ConnectionError('boom')):
            out = app_module.api._resolve_portrait([card('a', BANNER)])
        self.assertEqual(out[0]['cover'], BANNER)
        # Gagal tidak di-cache: percobaan berikutnya masih boleh resolve.
        self.assertNotIn("portrait_a", app_module.cache)

    def test_negative_result_is_cached(self):
        with patch.object(app_module.api, 'portrait_cover_api', return_value='') as m:
            app_module.api._resolve_portrait([card('a', BANNER)])
            app_module.api._resolve_portrait([card('a', BANNER)])
        self.assertEqual(m.call_count, 1)
        self.assertIn("portrait_a", app_module.cache)

    def test_positive_result_is_cached(self):
        with patch.object(app_module.api, 'portrait_cover_api', return_value=PORTRAIT) as m:
            app_module.api._resolve_portrait([card('a', BANNER)])
            out = app_module.api._resolve_portrait([card('a', BANNER)])
        self.assertEqual(m.call_count, 1)
        self.assertEqual(out[0]['cover'], PORTRAIT)

    def test_all_listing_items_are_resolved_not_capped(self):
        items = [card(f'slug-{i}', BANNER) for i in range(30)]
        with patch.object(app_module.api, 'portrait_cover_api', return_value='') as m:
            app_module.api._resolve_portrait(items)
        self.assertEqual(m.call_count, 30)

    def test_resolver_does_not_upscale_or_rewrite_url(self):
        """Hasil resolver dipakai apa adanya — tanpa param resize/upscale."""
        with patch.object(app_module.api, 'portrait_cover_api', return_value=PORTRAIT):
            out = app_module.api._resolve_portrait([card('a', BANNER)])
        self.assertEqual(out[0]['cover'], PORTRAIT)
        self.assertNotIn('resize=', out[0]['cover'])


class PortraitCoverApiTest(unittest.TestCase):
    def _resp(self, status=200, payload=None):
        r = MagicMock()
        r.status_code = status
        r.json.return_value = payload or {}
        r.raise_for_status.return_value = None
        return r

    def test_resize_param_is_stripped(self):
        resp = self._resp(payload={'thumbnail': PORTRAIT + '?w=500'})
        with patch.object(app_module.api, 'session') as s:
            s.get.return_value = resp
            self.assertEqual(app_module.api.portrait_cover_api('a'), PORTRAIT)

    def test_banner_thumbnail_is_rejected(self):
        resp = self._resp(payload={'thumbnail': BANNER})
        with patch.object(app_module.api, 'session') as s:
            s.get.return_value = resp
            self.assertEqual(app_module.api.portrait_cover_api('a'), '')

    def test_404_returns_empty(self):
        with patch.object(app_module.api, 'session') as s:
            s.get.return_value = self._resp(status=404)
            self.assertEqual(app_module.api.portrait_cover_api('a'), '')

    def test_protocol_relative_url_is_normalized(self):
        resp = self._resp(payload={'thumbnail': '//thumbnail.komiku.to/manga_thumbnail-x/c.jpg'})
        with patch.object(app_module.api, 'session') as s:
            s.get.return_value = resp
            self.assertEqual(app_module.api.portrait_cover_api('a'),
                             'https://thumbnail.komiku.to/manga_thumbnail-x/c.jpg')


class PortraitCoverValidationTest(unittest.TestCase):
    def test_banner_og_image_is_rejected_even_on_200(self):
        html = ('<html><head><meta property="og:image" content="'
                'https://thumbnail.komiku.to/manga_img_horizontal-x/banner.webp">'
                '</head><body></body></html>')
        with patch.object(app_module.web, '_fetch', return_value=html):
            self.assertEqual(app_module.web.portrait_cover('some-slug'), '')

    def test_portrait_thumbnail_is_accepted(self):
        html = ('<html><head><meta property="og:image" content="' + PORTRAIT + '">'
                '</head><body></body></html>')
        with patch.object(app_module.web, '_fetch', return_value=html):
            self.assertEqual(app_module.web.portrait_cover('some-slug'), PORTRAIT)

    def test_non_thumbnail_url_is_rejected(self):
        html = ('<html><head><meta property="og:image" content="'
                'https://img.komiku.org/banner-x.jpg"></head></html>')
        with patch.object(app_module.web, '_fetch', return_value=html):
            self.assertEqual(app_module.web.portrait_cover('some-slug'), '')


class ReaderAndFrontendContractTest(unittest.TestCase):
    def test_chapter_endpoint_returns_original_sources(self):
        from fastapi.testclient import TestClient
        urls = ['https://img.komiku.org/ch/page-1.webp',
                'https://img.komiku.org/ch/page-2.webp']
        with patch.object(app_module.api, 'chapter', return_value=urls):
            res = TestClient(app_module.app).get('/api/chapter/some-slug/12')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), urls)

    def test_frontend_keeps_srcset_240_400_800_sizes_fitcover(self):
        with open(app_module.INDEX_PATH, encoding='utf-8') as fh:
            html = fh.read()
        self.assertIn('opt(u, 240)} 240w', html)
        self.assertIn('opt(u, 400)} 400w', html)
        self.assertIn('opt(u, 800)} 800w', html)
        self.assertIn('sizes=', html)
        self.assertIn('function fitCover', html)
        self.assertIn('object-fit:contain', html)
        # Reader memakai source asli tanpa resize/format.
        self.assertIn('<img src="${IMG(u)}"', html)


if __name__ == '__main__':
    unittest.main()
