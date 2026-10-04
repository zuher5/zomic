import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module
from app import app, cache


class ApiRoutesTest(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.client = TestClient(app)

    def test_img_proxy_blocks_foreign_and_internal_hosts(self):
        for url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8000/health",
            "https://evil.example.com/x.png",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get("/api/img", params={"url": url}).status_code, 403)

    def test_img_proxy_rejects_non_http_scheme(self):
        self.assertEqual(self.client.get("/api/img", params={"url": "file:///etc/passwd"}).status_code, 400)

    def test_img_host_allowlist_matches_subdomains_only(self):
        allowed = app_module._img_host_allowed
        self.assertTrue(allowed("img.komiku.org"))
        self.assertTrue(allowed("komiku.org"))
        self.assertTrue(allowed("thumbnail.komiku.org:443"))
        self.assertTrue(allowed("cdn.uqni.net"))
        self.assertTrue(allowed("uqni.net"))
        self.assertTrue(allowed("cdn.voratoon.com"))
        self.assertTrue(allowed("cvr.voratoon.id"))
        self.assertFalse(allowed("komiku.org.evil.com"))
        self.assertFalse(allowed("uqni.net.evil.com"))
        self.assertFalse(allowed("notkomiku.org"))
        self.assertFalse(allowed(None))

    def test_catalog_validates_params(self):
        self.assertEqual(self.client.get("/api/catalog?page=0").status_code, 422)
        self.assertEqual(self.client.get("/api/catalog?page=999").status_code, 422)
        self.assertEqual(self.client.get("/api/catalog?type=bogus").status_code, 422)

    def test_search_requires_query(self):
        self.assertEqual(self.client.get("/api/search?q=").status_code, 422)

    def test_catalog_returns_pagination_envelope(self):
        payload = {
            "items": [{"slug": "a", "title": "A", "cover": "", "type": "Manga",
                       "genre": "Aksi", "status": "Ongoing", "chapter": ""}],
            "page": 2, "per_page": 50, "total": 7615, "total_pages": 153,
            "has_next": True, "filters": {"type": "", "letter": ""},
        }
        with patch.object(app_module.web, "catalog", return_value=payload) as m:
            res = self.client.get("/api/catalog?page=2&type=manga&letter=b")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["total"], 7615)
        m.assert_called_once_with(2, ctype="manga", letter="b")

    def test_responses_are_cached(self):
        with patch.object(app_module.web, "genres", return_value=[{"slug": "action", "name": "Action"}]) as m:
            self.client.get("/api/genres")
            self.client.get("/api/genres")
        m.assert_called_once()

    def test_genre_not_found_returns_404(self):
        empty = {"items": [], "page": 1, "per_page": 10, "genre": "nope", "has_next": False}
        with patch.object(app_module.web, "by_genre", return_value=empty), \
             patch.object(app_module.kiryuu, "by_genre", return_value={'items': []}), \
             patch.object(app_module.voratoon, "by_genre", return_value={'items': []}), \
             patch.object(app_module.sanka, "latest", return_value={'items': []}):
            self.assertEqual(self.client.get("/api/genre/nope").status_code, 404)

    def test_genre_includes_sanka_items(self):
        komiku_data = {"items": [{"title": "K", "slug": "k1", "cover": "", "genre": "Action", "status": "", "chapter": ""}],
                        "page": 1, "per_page": 10, "genre": "action", "has_next": False}
        sanka_items = [{'title': 'S Action', 'slug': 's1', 'cover': '', 'chapter': '1', 'source': 'westmanga', '_sanka_source': 'westmanga'}]
        with patch.object(app_module.web, "by_genre", return_value=komiku_data), \
             patch.object(app_module.api, "_resolve_portrait", side_effect=lambda xs: xs), \
             patch.object(app_module.kiryuu, "by_genre", return_value={'items': []}), \
             patch.object(app_module.voratoon, "by_genre", return_value={'items': []}), \
             patch.object(app_module.sanka, "latest", return_value={'items': sanka_items, 'page': 1, 'has_next': False}), \
             patch.object(app_module.sanka, "detail", return_value={'genres': [{'name': 'Action', 'slug': 'action'}]}):
            res = self.client.get("/api/genre/action")
        self.assertEqual(res.status_code, 200)
        slugs = [i['slug'] for i in res.json()['items']]
        self.assertIn('s1', slugs)

    def test_upstream_failure_becomes_502(self):
        import requests

        with patch.object(app_module.web, "catalog", side_effect=requests.ConnectionError("boom")):
            self.assertEqual(self.client.get("/api/catalog?page=1").status_code, 502)

    def test_chapter_prefers_kiryuu_images(self):
        kimgs = ["https://yuucdn/k1.webp"]
        gimgs = ["https://img.komiku.org/other.webp"]
        with patch.object(app_module.api, "_detail_json", return_value={"title": "X"}), \
             patch.object(app_module.kiryuu, "chapter_images", return_value=kimgs) as km, \
             patch.object(app_module.api, "chapter", return_value=gimgs):
            res = self.client.get("/api/chapter/some-slug/12")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), kimgs)  # kiryuu menang walau komiku ada
        km.assert_called_once_with("some-slug", "12")

    def test_chapter_falls_back_to_komiku(self):
        imgs = ["https://img.komiku.org/1.webp"]
        with patch.object(app_module.api, "_detail_json",
                           return_value={"title": "One Punch Man"}), \
             patch.object(app_module.kiryuu, "chapter_images", return_value=[]), \
             patch.object(app_module, "_resolve_kiryuu_slug", return_value="") as kr, \
             patch.object(app_module.api, "chapter", return_value=imgs):
            res = self.client.get("/api/chapter/some-slug/12")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), imgs)
        kr.assert_called_once_with("One Punch Man", exclude="some-slug")

    def test_chapter_404_when_komiku_404(self):
        import requests
        err = requests.HTTPError("not found")
        err.response = type("R", (), {"status_code": 404})()
        with patch.object(app_module.api, "_detail_json", return_value={}), \
             patch.object(app_module.kiryuu, "chapter_images", return_value=[]), \
             patch.object(app_module.api, "chapter", side_effect=err):
            self.assertEqual(self.client.get("/api/chapter/some-slug/12").status_code, 404)

    def test_chapter_both_empty_becomes_502(self):
        import requests
        with patch.object(app_module.api, "_detail_json", return_value={}), \
             patch.object(app_module.kiryuu, "chapter_images", return_value=[]), \
             patch.object(app_module.api, "chapter",
                           side_effect=requests.ConnectionError("boom")):
            self.assertEqual(self.client.get("/api/chapter/some-slug/12").status_code, 502)

    def test_komiku_chapter_uses_baca_slug_from_api_link(self):
        detail = {"chapters": [{"apiLink": "/baca-chapter/one-punch-man/310"}]}
        chap = {"images": [{"src": "https://img/1.webp", "fallbackSrc": ""}]}
        calls = []

        def fake_get(path, timeout=12):
            calls.append(path)
            return detail if path.startswith("/detail-komik/") else chap

        with patch.object(app_module.api, "_get", side_effect=fake_get):
            out = app_module.api.chapter("manga-one-punch-man", "310")
        self.assertEqual(out, ["https://img/1.webp"])
        self.assertIn("/baca-chapter/one-punch-man/310", calls)
        self.assertNotIn("/baca-chapter/manga-one-punch-man/310", calls)

    def test_komiku_chapter_empty_when_no_api_link(self):
        with patch.object(app_module.api, "_get",
                           return_value={"chapters": [{"apiLink": ""}]}) as g:
            self.assertEqual(app_module.api.chapter("no-link-slug", "1"), [])
        self.assertEqual(g.call_count, 1)  # hanya detail, tanpa baca

    def test_resolve_kiryuu_slug_exact_and_exclude(self):
        items = {"items": [
            {"slug": "manga-one-punch-man", "title": "One Punch Man"},
            {"slug": "one-punch-man", "title": "One Punch Man"},
        ]}
        with patch.object(app_module.kiryuu, "search", return_value=items):
            self.assertEqual(
                app_module._resolve_kiryuu_slug("One Punch Man",
                                                exclude="manga-one-punch-man"),
                "one-punch-man")
            self.assertEqual(
                app_module._resolve_kiryuu_slug("Other Title"), "manga-one-punch-man")

    def test_resolve_kiryuu_slug_empty_when_no_match(self):
        with patch.object(app_module.kiryuu, "search", return_value={"items": []}):
            self.assertEqual(app_module._resolve_kiryuu_slug("Ghost Title"), "")
        self.assertEqual(app_module._resolve_kiryuu_slug(""), "")
        self.assertEqual(app_module._norm_title("One-Punch Man!"), "onepunchman")

    def test_frontend_served_from_disk(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Zomic", res.text)

    def test_to_en_ago_converts_upstream_update_time(self):
        f = app_module._to_en_ago
        self.assertEqual(f("24 menit lalu"), "24 min ago")
        self.assertEqual(f("1 menit lalu"), "1 min ago")
        self.assertEqual(f("51 detik lalu"), "51 sec ago")
        self.assertEqual(f("1 jam lalu"), "1 hour ago")
        self.assertEqual(f("3 jam lalu"), "3 hours ago")
        self.assertEqual(f("1 hari lalu"), "1 day ago")
        self.assertEqual(f("2 hari lalu"), "2 days ago")
        self.assertEqual(f("3 bulan lalu"), "3 months ago")
        self.assertEqual(f("1 tahun lalu"), "1 year ago")
        # Tak dikenali -> apa adanya (kiryuu EN, kosong, '-')
        self.assertEqual(f("10 months ago"), "10 months ago")
        self.assertEqual(f(""), "")
        self.assertEqual(f("-"), "-")

    def test_popular_falls_back_to_kiryuu_when_komiku_fails(self):
        import requests as _req
        kiryuu_items = [
            {'slug': 'a', 'title': 'A', 'type': 'Manga', 'cover': ''},
            {'slug': 'b', 'title': 'B', 'type': 'Manhwa', 'cover': ''},
            {'slug': 'c', 'title': 'C', 'type': 'Manhua', 'cover': ''},
        ]
        with patch.object(app_module.api, 'popular',
                          side_effect=_req.ConnectionError('boom')), \
             patch.object(app_module.kiryuu, 'popular', return_value=kiryuu_items):
            res = self.client.get('/api/popular')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 3)
        self.assertEqual([g['key'] for g in data], ['manga', 'manhwa', 'manhua'])
        self.assertEqual(data[0]['items'][0]['slug'], 'a')
        self.assertEqual(data[0]['items'][0]['source'], 'kiryuu')

    def test_popular_empty_komiku_groups_kiryuu(self):
        import requests as _req
        with patch.object(app_module.api, 'popular', return_value=[]), \
             patch.object(app_module.kiryuu, 'popular',
                          return_value=[{'slug': 'x', 'title': 'X', 'type': 'manga', 'cover': ''}]):
            res = self.client.get('/api/popular')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['key'], 'manga')
        self.assertEqual(data[0]['title'], 'Manga Populer')
        self.assertEqual(data[0]['items'][0]['slug'], 'x')

    def test_popular_both_empty_becomes_502(self):
        import requests as _req
        with patch.object(app_module.api, 'popular',
                          side_effect=_req.ConnectionError('boom')), \
             patch.object(app_module.kiryuu, 'popular', return_value=[]), \
             patch.object(app_module.voratoon, 'popular', return_value=[]), \
             patch.object(app_module.sanka, 'latest', side_effect=_req.ConnectionError('boom')):
            self.assertEqual(self.client.get('/api/popular').status_code, 502)


class UnhandledExceptionTest(unittest.TestCase):
    """Exception tak terduga harus jadi 500 generik, bukan bocor traceback.

    Handler global di app.py menutup semua exception yang tidakanticipated
    (mis. requests.exceptions.SSLError dari scraper, yang tidak ditangkap
    retry_get). Tanpa itu, traceback penuh — termasuk path server dan nomor
    baris — terkirim ke klien publik.
    """

    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def _route_that_raises(self):
        from fastapi.routing import APIRoute

        def boom():
            raise RuntimeError('rahasia: /srv/zomic/app.py baris 4242')

        # Sisip di depan catch-all SPA, kalau tidak route ini tak akan pernah kena.
        return APIRoute(path='/__uji_boom', endpoint=boom, methods=['GET'])

    def test_unexpected_exception_returns_generic_500(self):
        app.router.routes.insert(0, self._route_that_raises())
        try:
            r = self.client.get('/__uji_boom')
        finally:
            app.router.routes.pop(0)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json(), {'detail': 'internal server error'})

    def test_unexpected_exception_does_not_leak_internals(self):
        app.router.routes.insert(0, self._route_that_raises())
        try:
            body = self.client.get('/__uji_boom').text
        finally:
            app.router.routes.pop(0)
        for leak in ('Traceback', 'RuntimeError', '/srv/zomic', 'app.py', '4242', 'line'):
            self.assertNotIn(leak, body, f'respons membocorkan internal: {leak!r}')

    def test_handler_does_not_mask_intentional_http_exceptions(self):
        # HTTPException yang disengaja (404 dari SPA fallback) harus tetap 404
        # dengan detail aslinya — handler global tidak boleh menutupinya jadi 500.
        r = self.client.get('/api/tidak-ada-xyz')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {'detail': 'not found'})

    def test_healthy_routes_unaffected(self):
        self.assertEqual(self.client.get('/health').status_code, 200)


class SankaRoutesTest(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.client = TestClient(app)

    def test_latest_still_200_with_sanka_items(self):
        sanka_items = [{'title': 'S', 'slug': 's1', 'cover': '', 'chapter': '1', 'source': 'westmanga'}]
        with patch.object(app_module.api, 'latest', return_value=[{'title': 'K', 'slug': 'k1', 'cover': '', 'type': 'Manga', 'genre': '', 'status': '', 'chapter': '', 'readers': ''}]), \
             patch.object(app_module.kiryuu, 'home', return_value={'items': []}), \
             patch.object(app_module.sanka, 'latest', return_value={'items': sanka_items, 'page': 1, 'has_next': False}) as sm:
            res = self.client.get('/api/latest')
        self.assertEqual(res.status_code, 200)
        sources = [it['source'] for it in res.json()]
        self.assertIn('komiku', sources)
        self.assertIn('sanka', sources)
        self.assertTrue(any(it['slug'] == 's1' for it in res.json()))
        from unittest.mock import call as _call
        self.assertIn(_call('westmanga', 1), sm.call_args_list)
        self.assertEqual(sm.call_count, 3)

    def test_sanka_latest_valid(self):
        payload = {'items': [{'title': 'A', 'slug': 'a', 'cover': '', 'chapter': '1', 'source': 'softkomik'}], 'page': 1, 'has_next': False}
        with patch.object(app_module.sanka, 'latest', return_value=payload) as m:
            res = self.client.get('/api/sanka/latest?source=softkomik&page=1')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), payload)
        m.assert_called_once_with('softkomik', 1)

    def test_sanka_latest_invalid_source_400(self):
        res = self.client.get('/api/sanka/latest?source=bogus&page=1')
        self.assertEqual(res.status_code, 400)

    def test_sanka_detail(self):
        payload = {'title': 'D', 'slug': 'd', 'chapters': [], 'source': 'westmanga'}
        with patch.object(app_module.sanka, 'detail', return_value=payload) as m:
            res = self.client.get('/api/sanka/detail/westmanga/some-slug')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), payload)
        m.assert_called_once_with('westmanga', 'some-slug')

    def test_sanka_detail_invalid_source_400(self):
        self.assertEqual(self.client.get('/api/sanka/detail/bogus/x').status_code, 400)

    def test_sanka_chapter(self):
        imgs = ['https://img/1.webp']
        with patch.object(app_module.sanka, 'chapter_images', return_value=imgs) as m:
            res = self.client.get('/api/sanka/chapter/komikstation/comic-x/chapter-1')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'images': imgs})
        m.assert_called_once_with('komikstation', 'comic-x', 'chapter-1')

    def test_sanka_chapter_invalid_source_400(self):
        self.assertEqual(self.client.get('/api/sanka/chapter/bogus/c/ch').status_code, 400)


class VoratoonRoutesTest(unittest.TestCase):
    def setUp(self):
        cache.clear()
        self.client = TestClient(app)

    def test_img_referer_for_voratoon(self):
        self.assertEqual(app_module._img_referer("https://cdn.voratoon.com/img/01.jpg"), "https://v5.voratoon.com/")
        self.assertEqual(app_module._img_referer("https://cvr.voratoon.id/cover.webp"), "https://v5.voratoon.com/")

    def test_latest_includes_voratoon(self):
        vora_items = [{'title': 'V Comic', 'slug': 'vt-v1', 'cover': '', 'chapter': '1', 'source': 'voratoon'}]
        with patch.object(app_module.api, 'latest', return_value=[]), \
             patch.object(app_module.kiryuu, 'home', return_value={'items': []}), \
             patch.object(app_module.voratoon, 'latest', return_value=vora_items), \
             patch.object(app_module.sanka, 'latest', return_value={'items': []}):
            res = self.client.get('/api/latest')
        self.assertEqual(res.status_code, 200)
        slugs = [it['slug'] for it in res.json()]
        self.assertIn('vt-v1', slugs)

    def test_search_includes_voratoon(self):
        vora_items = [{'title': 'V Magic', 'slug': 'vt-v-magic', 'cover': '', 'chapter': '1', 'source': 'voratoon'}]
        with patch.object(app_module.web, 'search', return_value={'items': []}), \
             patch.object(app_module.kiryuu, 'search', return_value={'items': []}), \
             patch.object(app_module.voratoon, 'search', return_value={'items': vora_items}), \
             patch.object(app_module.sanka, 'latest', return_value={'items': []}):
            res = self.client.get('/api/search?q=magic')
        self.assertEqual(res.status_code, 200)
        slugs = [it['slug'] for it in res.json()['items']]
        self.assertIn('vt-v-magic', slugs)

    def test_detail_voratoon_slug(self):
        payload = {
            'title': 'Magic Emperor', 'slug': 'vt-magic-emperor',
            'chapters': [{'title': 'Chapter 1', 'ch': '1', 'date': '', 'url': '/read/vt-magic-emperor/1'}],
            'source': 'voratoon'
        }
        with patch.object(app_module.voratoon, 'detail', return_value=payload) as m:
            res = self.client.get('/api/detail/vt-magic-emperor')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['title'], 'Magic Emperor')
        m.assert_called_once_with('vt-magic-emperor')

    def test_detail_voratoon_404(self):
        with patch.object(app_module.voratoon, 'detail', return_value=None):
            res = self.client.get('/api/detail/vt-non-exist')
        self.assertEqual(res.status_code, 404)

    def test_chapter_voratoon_slug(self):
        imgs = ['https://cdn.voratoon.com/img/01.jpg', 'https://cdn.voratoon.com/img/02.jpg']
        with patch.object(app_module.voratoon, 'chapter_images', return_value=imgs) as m:
            res = self.client.get('/api/chapter/vt-magic-emperor/1')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), imgs)
        m.assert_called_once_with('vt-magic-emperor', '1')

    def test_chapter_voratoon_404(self):
        with patch.object(app_module.voratoon, 'chapter_images', return_value=[]):
            res = self.client.get('/api/chapter/vt-magic-emperor/999')
        self.assertEqual(res.status_code, 404)

    def test_voratoon_direct_routes(self):
        with patch.object(app_module.voratoon, 'latest', return_value=[{'slug': 'vt-1'}]) as m:
            r1 = self.client.get('/api/voratoon/latest?page=1')
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r1.json()['items'], [{'slug': 'vt-1'}])

        with patch.object(app_module.voratoon, 'detail', return_value={'title': 'X'}) as m:
            r2 = self.client.get('/api/voratoon/detail/x')
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json()['title'], 'X')

        with patch.object(app_module.voratoon, 'chapter_images', return_value=['https://cdn/1.jpg']) as m:
            r3 = self.client.get('/api/voratoon/chapter/x/1')
            self.assertEqual(r3.status_code, 200)
            self.assertEqual(r3.json()['images'], ['https://cdn/1.jpg'])


if __name__ == "__main__":
    unittest.main()
