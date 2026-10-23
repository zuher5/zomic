import unittest
from unittest.mock import patch

import requests
from fastapi.testclient import TestClient

import app as app_module
from kiryuu_web import KiryuuWeb, _initial


def _kcard(slug, title, ctype='Manga'):
    return {
        'slug': slug, 'title': title, 'cover': 'https://img.kiryuu.to/x.jpg',
        'type': ctype, 'genre': 'Action', 'status': 'Ongoing', 'chapter': '12',
        'rating': '8.5', 'source': 'kiryuu',
    }


KIRYUU_PAGE = {
    'items': [
        _kcard('alpha-one', 'Alpha One'),
        _kcard('beta-two', 'Beta Two', 'Manhwa'),
        _kcard('aleph-three', 'Aleph Three', 'Manhua'),
    ],
    'page': 1, 'per_page': 24, 'total': None, 'total_pages': 316,
    'has_next': True, 'raw_count': 3, 'filters': {'type': '', 'letter': ''},
}


class CatalogFallbackTest(unittest.TestCase):
    """/api/catalog tidak boleh bergantung pada komiku.org HTML (403 CF)."""

    def setUp(self):
        app_module.cache.clear()
        app_module._RATE_BUCKETS.clear()
        p = patch.object(app_module.api, 'latest', side_effect=lambda *_a, **_k: [])
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(app_module.cache.clear)
        self.addCleanup(app_module._RATE_BUCKETS.clear)
        self.client = TestClient(app_module.app)

    def _get(self, qs='', komiku=None, kiryuu=None, shin=None):
        """komiku/kiryuu/shin = nilai balik atau Exception."""

        def _komiku(*a, **k):
            if isinstance(komiku, Exception):
                raise komiku
            return dict(komiku or {})

        def _kiryuu(*a, **k):
            if isinstance(kiryuu, Exception):
                raise kiryuu
            return dict(kiryuu or {})

        def _shin(*a, **k):
            if isinstance(shin, Exception):
                raise shin
            return list(shin or [])

        for ctx in (
            patch.object(app_module.web, 'catalog', side_effect=_komiku),
            patch.object(app_module.kiryuu, 'catalog', side_effect=_kiryuu),
            patch.object(app_module.shinigami, 'latest', side_effect=_shin),
        ):
            ctx.start()
            self.addCleanup(ctx.stop)
        app_module.cache.clear()
        return self.client.get('/api/catalog' + qs)

    @staticmethod
    def _forbidden():
        return requests.HTTPError(
            '403 Client Error: Forbidden',
            response=_Resp(403),
        )

    def test_filter_kosong_tetap_200(self):
        # Halaman valid tapi tidak ada manhwa: jangan 502, jangan jatuh ke
        # sumber lain; kembalikan grid kosong dari kiryuu.
        # Filter dilakukan DI DALAM kiryuu.catalog (di sini di-mock), jadi
        # fixture sudah berbentuk hasil filter: 0 item tapi raw_count > 0.
        only_manga = {
            'items': [],
            'page': 1, 'per_page': 24, 'total': None, 'total_pages': 316,
            'has_next': True, 'raw_count': 1,
            'filters': {'type': 'manhwa', 'letter': ''},
        }
        res = self._get('?type=manhwa', komiku=self._forbidden(), kiryuu=only_manga)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body['source'], 'kiryuu')
        self.assertEqual(body['items'], [])

    def test_komiku_403_jatuh_ke_kiryuu(self):
        res = self._get(komiku=self._forbidden(), kiryuu=KIRYUU_PAGE)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body['source'], 'kiryuu')
        self.assertTrue(body['degraded'])
        self.assertFalse(body['filters_supported']['letter'])
        self.assertEqual(len(body['items']), 3)
        self.assertTrue(all(c['source'] == 'kiryuu' for c in body['items']))

    def test_respons_degraded_cache_lebih_singkat(self):
        res = self._get(komiku=self._forbidden(), kiryuu=KIRYUU_PAGE)
        self.assertIn('s-maxage=300', res.headers['cache-control'])

    def test_komiku_hidup_tidak_degraded(self):
        payload = {
            'items': [{'slug': 'komik', 'title': 'Komik', 'cover': '', 'type': 'Manga'}],
            'page': 1, 'per_page': 50, 'total': 7615, 'total_pages': 153,
            'has_next': True, 'filters': {'type': '', 'letter': ''},
        }
        res = self._get(komiku=payload, kiryuu=KIRYUU_PAGE)
        body = res.json()
        self.assertEqual(body['source'], 'komiku')
        self.assertFalse(body['degraded'])
        self.assertTrue(body['filters_supported']['letter'])
        self.assertEqual(body['items'][0]['slug'], 'komik')

    def test_kiryuu_gagal_jatuh_ke_shinigami(self):
        shn = [{'slug': 'shn-1', 'title': 'Shn One', 'cover': '', 'type': 'Manhwa'}]
        res = self._get(komiku=self._forbidden(), kiryuu=requests.ConnectionError('x'), shin=shn)
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body['source'], 'shinigami')
        self.assertEqual(body['items'][0]['slug'], 'shn-1')
        self.assertFalse(body['filters_supported']['type'])

    def test_semua_sumber_gagal_502(self):
        res = self._get(
            komiku=self._forbidden(),
            kiryuu=requests.ConnectionError('x'),
            shin=requests.ConnectionError('y'),
        )
        self.assertEqual(res.status_code, 502)
        # Detail generik dipertahankan (alasan lengkap ada di log) agar
        # kontrak error endpoint lain tidak berubah.
        self.assertEqual(res.json()['detail'], 'upstream error')

    def test_circuit_breaker_melewati_komiku(self):
        with patch.object(app_module.web, 'catalog',
                          side_effect=self._forbidden()) as m:
            with patch.object(app_module.kiryuu, 'catalog', return_value=dict(KIRYUU_PAGE)):
                self.client.get('/api/catalog?page=1')
                # Request kedua (kunci cache beda) tidak boleh memanggil komiku.
                self.client.get('/api/catalog?page=2&type=manga')
        self.assertEqual(m.call_count, 1)
        self.assertTrue(app_module._komiku_html_blocked())

    def test_breaker_tidak_aktif_untuk_5xx(self):
        err = requests.HTTPError('503 upstream', response=_Resp(503))
        with patch.object(app_module.web, 'catalog', side_effect=err), \
             patch.object(app_module.kiryuu, 'catalog', return_value=dict(KIRYUU_PAGE)):
            self.client.get('/api/catalog?page=1')
        self.assertFalse(app_module._komiku_html_blocked())


class _Resp:
    """Response minimal untuk HTTPError (tanpa jaringan)."""

    def __init__(self, status_code):
        self.status_code = status_code


class KiryuuCatalogTest(unittest.TestCase):
    """Uji unit KiryuuWeb.catalog (fetch di-mock)."""

    def setUp(self):
        self.k = KiryuuWeb()
        self.raw = (
            '<a href="/manga/alpha-one/">Alpha One</a>'
            '<a href="/manga/page/2/">2</a>'
            '<a href="/manga/page/3/">3</a>'
        )

    def _run(self, page=1, ctype=None, letter=None):
        with patch.object(self.k, '_fetch', return_value=self.raw) as m, \
             patch.object(self.k, '_parse_listing', return_value=[
                 _kcard('alpha-one', 'Alpha One'),
                 _kcard('beta-two', 'Beta Two', 'Manhwa'),
             ]):
            data = self.k.catalog(page, ctype=ctype, letter=letter)
        return data, m

    def test_url_arsip_per_halaman(self):
        _, m = self._run(page=1)
        self.assertEqual(m.call_args[0][0], 'https://v7.kiryuu.to/manga/')
        _, m = self._run(page=7)
        self.assertEqual(m.call_args[0][0], 'https://v7.kiryuu.to/manga/page/7/')

    def test_halaman_di_atas_batas_kosong(self):
        data, m = self._run(page=400)
        self.assertEqual(data['items'], [])
        self.assertFalse(data['has_next'])
        m.assert_not_called()

    def test_filter_type_dan_letter(self):
        data, _ = self._run(ctype='manhwa')
        self.assertEqual([c['slug'] for c in data['items']], ['beta-two'])
        data, _ = self._run(letter='a')
        self.assertEqual([c['slug'] for c in data['items']], ['alpha-one'])

    def test_has_next_dari_kartu_mentah(self):
        # Filter sepi tidak boleh mematikan paginasi.
        data, _ = self._run(ctype='manhwa')
        self.assertTrue(data['has_next'])
        self.assertEqual(data['source'] if 'source' in data else None, None)
        self.assertEqual(data['items'][0]['source'], 'kiryuu')

    def test_total_pages_dibatasi(self):
        data, _ = self._run(page=316)
        self.assertEqual(data['total_pages'], 316)
        self.assertFalse(data['has_next'])
        self.assertIsNone(data['total'])  # jangan tampilkan angka palsu

    def test_raw_count_isi_walau_filter_kosong(self):
        data, _ = self._run(ctype='manhwa')
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['raw_count'], 2)

    def test_initial_ignores_punctuation(self):
        self.assertEqual(_initial('— Alpha'), 'A')
        self.assertEqual(_initial("[Oshi no Ko]"), 'O')
        self.assertEqual(_initial(''), '')


if __name__ == '__main__':
    unittest.main()
