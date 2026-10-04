"""Unit tests untuk sanka_web.py — normalisasi REST API Sanka Vollerei."""

import unittest

from sanka_web import SankaWeb, _norm_status, _strip_html

# ---------- FIXTURES INLINE (tanpa jaringan) ----------

SOFTKOMIK_HOME = {
    "success": True,
    "data": {
        "trending": [],
        "latest": [
            {"title": "Mark of the Fool", "slug": "mark-of-the-fool-bahasa-indonesia",
             "image": "https://cover/mark.webp", "latestChapter": "Chapter 004",
             "type": "manhwa", "status": "ongoing"},
            {"title": "Solo Swordmaster", "slug": "solo-swordmaster-bahasa-indonesia",
             "image": "https://cover/solo.webp", "latestChapter": "Chapter 020",
             "type": "manhwa", "status": "tamat"},
        ],
    },
}

WESTMANGA_HOME = {
    "success": True,
    "data": {
        "mirror_update": [
            {"title": "Girl-Go", "slug": "girl-go", "cover": "https://storage/gg.jpg",
             "content_type": "comic", "status": "ongoing",
             "lastChapters": [{"number": "52", "slug": "girl-go-chapter-52",
                               "created_at": {"formatted": "26 Sep 2026 14:37"}}]},
        ],
    },
}

KOMIKSTATION_HOME = {
    "success": True,
    "trending": [],
    "latestUpdates": [
        {"title": "A Kind Intruder", "slug": "a-kind-intruder",
         "imageSrc": "https://komikstation.org/a.webp",
         "chapters": [{"slug": "a-kind-intruder-chapter-50", "title": "Ch. 50",
                       "timeAgo": "2 menit lalu"}]},
    ],
}

SOFTKOMIK_DETAIL = {
    "success": True,
    "data": {
        "title": "Mark of the Fool", "slug": "mark-of-the-fool-bahasa-indonesia",
        "image": "https://cover/mark.webp", "status": "ongoing", "type": "manhwa",
        "author": None, "rating": {"average": 0, "count": 0},
        "synopsis": "Alex ingin jadi penyihir.",
        "genres": ["Action", "Fantasy"],
        "chapters": [
            {"title": "Chapter 002", "slug": "002"},
            {"title": "Chapter 001", "slug": "001"},
        ],
    },
}

WESTMANGA_DETAIL = {
    "success": True,
    "data": {
        "title": "Girl-Go", "slug": "girl-go", "cover": "https://storage/gg.jpg",
        "status": "ongoing", "content_type": "comic", "author": "Cutie Pong",
        "rating": 7, "sinopsis": "<p>Di atas papan Go.</p>",
        "genres": [{"id": 6, "name": "Drama"}, {"id": 23, "name": "Psychological"}],
        "chapters": [
            {"number": "52", "slug": "girl-go-chapter-52",
             "updated_at": {"formatted": "26 Sep 2026 14:37"}},
            {"number": "51", "slug": "girl-go-chapter-51",
             "updated_at": {"formatted": "18 Sep 2026 00:51"}},
        ],
    },
}

KOMIKSTATION_DETAIL = {
    "success": True,
    "title": "A Kind Intruder", "slug": "a-kind-intruder",
    "imageSrc": "https://komikstation.org/a.webp", "status": "Berjalan",
    "type": "Manhwa", "author": "Ini", "rating": "7.3",
    "synopsis": "Ihan tiba-tiba harus tinggal serumah.",
    "genres": [{"name": "Drama"}, {"name": "Romance"}],
    "chapters": [
        {"title": "Chapter 50", "slug": "a-kind-intruder-chapter-50", "date": "Juni 30, 2026"},
        {"title": "Chapter 49", "slug": "a-kind-intruder-chapter-49", "date": "Juni 30, 2026"},
    ],
}

SOFTKOMIK_CHAPTER = {
    "success": True,
    "data": {"title": "Chapter 004", "slug": "mark-of-the-fool-bahasa-indonesia",
             "images": ["https://img/1.webp", "https://img/2.webp"],
             "imagesproxy": ["https://proxy/1.webp"]},
}

SOFTKOMIK_CHAPTER_EMPTY = {
    "success": True,
    "data": {"title": "Chapter 004", "images": [],
             "imagesproxy": ["https://proxy/1.webp", "https://proxy/2.webp"]},
}

WESTMANGA_CHAPTER = {
    "success": True,
    "data": {"slug": "girl-go-chapter-52",
             "images": ["https://storage/52-1.jpg", "https://storage/52-2.jpg"]},
}

KOMIKSTATION_CHAPTER = {
    "success": True,
    "title": "A Kind Intruder Chapter 50",
    "images": ["https://klikcdn/001.jpg", "https://klikcdn/002.jpg"],
}

DETAIL_BY_PATH = {
    "/comic/softkomik/detail/mark-of-the-fool-bahasa-indonesia": SOFTKOMIK_DETAIL,
    "/comic/westmanga/detail/girl-go": WESTMANGA_DETAIL,
    "/comic/komikstation/manga/a-kind-intruder": KOMIKSTATION_DETAIL,
}

CHAPTER_BY_PATH = {
    "/comic/softkomik/chapter/mark-of-the-fool-bahasa-indonesia/004": SOFTKOMIK_CHAPTER,
    "/comic/westmanga/chapter/girl-go-chapter-52": WESTMANGA_CHAPTER,
    "/comic/komikstation/chapter/a-kind-intruder-chapter-50": KOMIKSTATION_CHAPTER,
}

HOME_BY_PATH = {
    "/comic/softkomik/home": SOFTKOMIK_HOME,
    "/comic/westmanga/home": WESTMANGA_HOME,
    "/comic/komikstation/home": KOMIKSTATION_HOME,
}


def _router(mapping):
    def _get(path, **kw):
        for prefix, body in mapping.items():
            if path.startswith(prefix):
                return body
        raise AssertionError(f"path tidak dikenal di fixture: {path}")
    return _get


class TestLatest(unittest.TestCase):
    def setUp(self):
        self.web = SankaWeb()

    def test_softkomik_latest(self):
        self.web._get = _router(HOME_BY_PATH)
        d = self.web.latest('softkomik', 1)
        self.assertEqual(d['page'], 1)
        self.assertFalse(d['has_next'])
        self.assertEqual(len(d['items']), 2)
        first = d['items'][0]
        self.assertEqual(first['title'], 'Mark of the Fool')
        self.assertEqual(first['slug'], 'mark-of-the-fool-bahasa-indonesia')
        self.assertEqual(first['cover'], 'https://cover/mark.webp')
        self.assertEqual(first['chapter'], 'Chapter 004')
        self.assertEqual(first['source'], 'softkomik')

    def test_westmanga_latest_mirror_update(self):
        self.web._get = _router(HOME_BY_PATH)
        d = self.web.latest('westmanga', 1)
        self.assertEqual(len(d['items']), 1)
        item = d['items'][0]
        self.assertEqual(item['cover'], 'https://storage/gg.jpg')
        self.assertEqual(item['chapter'], '52')
        self.assertEqual(item['source'], 'westmanga')

    def test_komikstation_latest_updates(self):
        self.web._get = _router(HOME_BY_PATH)
        d = self.web.latest('komikstation', 1)
        self.assertEqual(len(d['items']), 1)
        item = d['items'][0]
        self.assertEqual(item['cover'], 'https://komikstation.org/a.webp')
        self.assertEqual(item['chapter'], 'Ch. 50')
        self.assertEqual(item['source'], 'komikstation')

    def test_latest_has_next_from_pagination(self):
        body = dict(SOFTKOMIK_HOME)
        body['pagination'] = {'hasNext': True}
        self.web._get = lambda path, **kw: body
        self.assertTrue(self.web.latest('softkomik', 1)['has_next'])

    def test_latest_invalid_source(self):
        with self.assertRaises(ValueError):
            self.web.latest('mangasusuku')


class TestDetail(unittest.TestCase):
    def setUp(self):
        self.web = SankaWeb()
        self.web._get = _router(DETAIL_BY_PATH)

    def test_softkomik_detail(self):
        d = self.web.detail('softkomik', 'mark-of-the-fool-bahasa-indonesia')
        self.assertEqual(d['title'], 'Mark of the Fool')
        self.assertEqual(d['cover'], 'https://cover/mark.webp')
        self.assertEqual(d['status'], 'Ongoing')
        self.assertEqual(d['author'], '')
        self.assertEqual(d['rating'], '0')
        self.assertEqual(d['genres'], ['Action', 'Fantasy'])
        self.assertEqual(d['source'], 'softkomik')
        # Newest-first upstream → dibalik jadi oldest-first.
        self.assertEqual([c['slug'] for c in d['chapters']], ['001', '002'])

    def test_westmanga_detail(self):
        d = self.web.detail('westmanga', 'girl-go')
        self.assertEqual(d['title'], 'Girl-Go')
        self.assertEqual(d['cover'], 'https://storage/gg.jpg')
        self.assertEqual(d['status'], 'Ongoing')
        self.assertEqual(d['author'], 'Cutie Pong')
        self.assertEqual(d['rating'], '7')
        self.assertNotIn('<p>', d['synopsis'])
        self.assertEqual(d['genres'], ['Drama', 'Psychological'])
        self.assertEqual(d['chapters'][0]['title'], 'Chapter 51')
        self.assertEqual(d['chapters'][0]['date'], '18 Sep 2026 00:51')
        self.assertEqual(d['chapters'][1]['slug'], 'girl-go-chapter-52')

    def test_komikstation_detail(self):
        d = self.web.detail('komikstation', 'a-kind-intruder')
        self.assertEqual(d['title'], 'A Kind Intruder')
        self.assertEqual(d['status'], 'Ongoing')  # "Berjalan" dinormalisasi
        self.assertEqual(d['type'], 'Manhwa')
        self.assertEqual(d['rating'], '7.3')
        self.assertEqual(d['genres'], ['Drama', 'Romance'])
        self.assertEqual(d['chapters'][0]['slug'], 'a-kind-intruder-chapter-49')
        self.assertEqual(d['chapters'][1]['date'], 'Juni 30, 2026')

    def test_detail_empty_slug(self):
        with self.assertRaises(ValueError):
            self.web.detail('softkomik', '')


class TestChapterImages(unittest.TestCase):
    def setUp(self):
        self.web = SankaWeb()

    def test_softkomik_images(self):
        self.web._get = _router(CHAPTER_BY_PATH)
        imgs = self.web.chapter_images('softkomik', 'mark-of-the-fool-bahasa-indonesia', '004')
        self.assertEqual(imgs, ['https://img/1.webp', 'https://img/2.webp'])

    def test_softkomik_imagesproxy_fallback(self):
        self.web._get = lambda path, **kw: SOFTKOMIK_CHAPTER_EMPTY
        imgs = self.web.chapter_images('softkomik', 'mark-of-the-fool-bahasa-indonesia', '004')
        self.assertEqual(imgs, ['https://proxy/1.webp', 'https://proxy/2.webp'])

    def test_softkomik_path_includes_comic_slug(self):
        seen = []
        def fake_get(path, **kw):
            seen.append(path)
            return SOFTKOMIK_CHAPTER
        self.web._get = fake_get
        self.web.chapter_images('softkomik', 'mark-of-the-fool-bahasa-indonesia', '004')
        self.assertEqual(seen[0], '/comic/softkomik/chapter/mark-of-the-fool-bahasa-indonesia/004')

    def test_westmanga_images(self):
        self.web._get = _router(CHAPTER_BY_PATH)
        imgs = self.web.chapter_images('westmanga', 'girl-go', 'girl-go-chapter-52')
        self.assertEqual(len(imgs), 2)
        self.assertTrue(imgs[0].startswith('https://storage/'))

    def test_komikstation_images(self):
        self.web._get = _router(CHAPTER_BY_PATH)
        imgs = self.web.chapter_images('komikstation', 'a-kind-intruder', 'a-kind-intruder-chapter-50')
        self.assertEqual(imgs[0], 'https://klikcdn/001.jpg')

    def test_empty_chapter_slug(self):
        self.assertEqual(self.web.chapter_images('westmanga', 'girl-go', ''), [])


class TestHelpers(unittest.TestCase):
    def test_strip_html(self):
        self.assertEqual(_strip_html('<p>Halo <b>dunia</b></p>'), 'Halo dunia')
        self.assertEqual(_strip_html(''), '')
        self.assertEqual(_strip_html(None), '')

    def test_norm_status(self):
        self.assertEqual(_norm_status('Berjalan'), 'Ongoing')
        self.assertEqual(_norm_status('tamat'), 'Completed')
        self.assertEqual(_norm_status('ongoing'), 'Ongoing')


if __name__ == '__main__':
    unittest.main()
