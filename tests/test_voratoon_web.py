import unittest
from types import SimpleNamespace
from unittest.mock import patch

from voratoon_web import VoratoonWeb, _clean_text, _fix_cover, _humanize_slug

LATEST_HTML = """
<html><body>
<article>
  <div class="update-series-card">
    <a href="/series/feasting-lord-in-another-world">
      <span class="update-series-card_title__abc">Feasting Lord in Another World</span>
    </a>
    <img src="/api/cover?src=https%3A%2F%2Fcvr.voratoon.id%2Fcover.webp" />
    <a href="/series/feasting-lord-in-another-world/chapter/15">
      <span class="update-series-card_time__xyz">1 jam lalu</span>
    </a>
  </div>
</article>
<article>
  <div class="update-series-card">
    <a href="/series/magic-emperor">
      <span class="update-series-card_title__abc">Magic Emperor</span>
    </a>
    <img src="/api/cover?src=https%3A%2F%2Fcvr.voratoon.id%2Fkaisar.webp" />
    <a href="/series/magic-emperor/chapter/920">
      <span class="update-series-card_time__xyz">2 jam lalu</span>
    </a>
  </div>
</article>
</body></html>
"""

BROWSE_HTML = """
<html><body>
<article class="card">
  <a class="card-title" href="/series/magic-emperor">Magic Emperor</a>
  <img src="/api/cover?src=https%3A%2F%2Fcvr.voratoon.id%2Fkaisar.webp" />
  <span class="tag-chapters">Chapter 920</span>
  <span data-status-tone="ongoing">Ongoing</span>
</article>
<a href="/browse?q=magic&page=2">Next</a>
</body></html>
"""

RANKING_HTML = """
<html><body>
<a class="comic-row" href="/series/magic-emperor">
  <span class="comic-rank-num">1</span>
  <img alt="Cover Magic Emperor" src="/api/cover?src=https%3A%2F%2Fcvr.voratoon.id%2Fkaisar.webp" />
  <h2>Magic Emperor</h2>
</a>
</body></html>
"""

DETAIL_HTML = """
<html>
<head>
<script type="application/ld+json">
[
  {
    "@context": "https://schema.org",
    "@type": "ComicSeries",
    "name": "Magic Emperor",
    "alternateName": "Demonic Emperor",
    "description": "Kisah kaisar sihir terlahir kembali.",
    "genre": ["Action", "Fantasy", "Martial Arts"],
    "image": "https://cvr.voratoon.id/kaisar.webp?sig=123&x=1",
    "author": {"@type": "Person", "name": "Nightingale"},
    "numberOfEpisodes": 3
  }
]
</script>
</head>
<body>
<div class="info-grid">
  <div class="info-item"><span class="info-label">Status</span><strong><span data-status-tone="ongoing">ONGOING</span></strong></div>
  <div class="info-item"><span class="info-label">Format</span><strong><!-- -->MANHUA</strong></div>
</div>
<div class="chapter-list">
  <a class="chapter-item" href="/series/magic-emperor/chapter/3">
    <span class="chapter-number">Chapter 3</span>
    <span class="chapter-date">1 hari lalu</span>
  </a>
  <a class="chapter-item" href="/series/magic-emperor/chapter/1">
    <span class="chapter-number">Chapter 1</span>
    <span class="chapter-date">3 hari lalu</span>
  </a>
  <a class="chapter-item" href="/series/magic-emperor/chapter/2">
    <span class="chapter-number">Chapter 2</span>
    <span class="chapter-date">2 hari lalu</span>
  </a>
</div>
</body></html>
"""

CHAPTER_HTML = """
<html><body>
<div class="reader">
  <img data-chapter-page="https://cdn.voratoon.com/img/01.jpg" />
  <img data-chapter-page="https://cdn.voratoon.com/img/02.jpg" />
  <img data-chapter-page="https://cdn.voratoon.com/img/03.jpg" />
</div>
</body></html>
"""


def _mock_web(mapping):
    web = VoratoonWeb()
    def fake_get(url, **kw):
        for k in sorted(mapping.keys(), key=len, reverse=True):
            if k in url:
                payload = mapping[k]
                if isinstance(payload, int):
                    resp = SimpleNamespace(status_code=payload, text='')
                    return resp
                resp = SimpleNamespace(status_code=200, text=payload)
                return resp
        return SimpleNamespace(status_code=404, text='Not Found')
    return web, fake_get


class TestVoratoonWeb(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(_clean_text("<b>Halo &amp; Dunia</b> <!-- comment -->"), "Halo & Dunia")
        self.assertEqual(_humanize_slug("magic-emperor"), "Magic Emperor")
        self.assertEqual(_fix_cover("/api/cover?src=abc"), "https://v5.voratoon.com/api/cover?src=abc")
        self.assertEqual(_fix_cover("https://cvr.voratoon.id/img.webp"), "https://cvr.voratoon.id/img.webp")

    def test_latest(self):
        web, fake_get = _mock_web({'/updates': LATEST_HTML})
        with patch.object(web, '_fetch', side_effect=lambda u, **kw: fake_get(u).text):
            items = web.latest(1)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]['slug'], 'vt-feasting-lord-in-another-world')
            self.assertEqual(items[0]['title'], 'Feasting Lord in Another World')
            self.assertEqual(items[0]['source'], 'voratoon')
            self.assertEqual(items[1]['slug'], 'vt-magic-emperor')

    def test_latest_next_data(self):
        stream_html = r"""
        <html><body>
        <script>self.__next_f.push([1,"7:[\"$\",\"$L8\",null,{\"initialData\":[{\"id\":\"c1\",\"slug\":\"my-divine-power\",\"title\":\"My Divine Power\",\"cover\":\"https://cvr.voratoon.id/p.webp\",\"format\":\"MANHUA\",\"genres\":[{\"name\":\"Action\"},{\"name\":\"Fantasy\"}],\"chapters\":[{\"chapterNumber\":50,\"updatedAt\":\"2025-01-01T00:00:00Z\"}]}]}]"])</script>
        </body></html>
        """
        web, fake_get = _mock_web({'/updates': stream_html})
        with patch.object(web, '_fetch', side_effect=lambda u, **kw: fake_get(u).text):
            items = web.latest(1)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['slug'], 'vt-my-divine-power')
            self.assertEqual(items[0]['title'], 'My Divine Power')
            self.assertEqual(items[0]['type'], 'Manhua')
            self.assertEqual(items[0]['genre'], 'Action, Fantasy')
            self.assertEqual(items[0]['chapter'], 'Chapter 50')

    def test_search(self):
        web, fake_get = _mock_web({'/browse?q=magic': BROWSE_HTML})
        with patch.object(web, '_fetch', side_effect=lambda u, **kw: fake_get(u).text):
            res = web.search('magic', 1)
            self.assertEqual(len(res['items']), 1)
            self.assertEqual(res['items'][0]['slug'], 'vt-magic-emperor')
            self.assertEqual(res['items'][0]['status'], 'Ongoing')
            self.assertTrue(res['has_next'])

    def test_popular(self):
        web, fake_get = _mock_web({'/ranking': RANKING_HTML})
        with patch.object(web, '_fetch', side_effect=lambda u, **kw: fake_get(u).text):
            items = web.popular()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['slug'], 'vt-magic-emperor')
            self.assertEqual(items[0]['title'], 'Magic Emperor')
            self.assertEqual(items[0]['type'], 'Manhwa')
            self.assertTrue(items[0]['cover'].startswith('https://v5.voratoon.com/api/cover'))

    def test_detail(self):
        web, fake_get = _mock_web({'/series/magic-emperor': DETAIL_HTML})
        with patch.object(web, '_fetch', side_effect=lambda u, **kw: fake_get(u).text):
            d = web.detail('vt-magic-emperor')
            self.assertIsNotNone(d)
            self.assertEqual(d['title'], 'Magic Emperor')
            self.assertEqual(d['alt_title'], 'Demonic Emperor')
            self.assertEqual(d['author'], 'Nightingale')
            self.assertEqual(d['type'], 'Manhua')
            self.assertEqual(d['status'], 'Ongoing')
            self.assertEqual(d['source'], 'voratoon')
            self.assertEqual(len(d['chapters']), 3)
            # Chapter terurut menaik (Chapter 1 duluan)
            self.assertEqual(d['chapters'][0]['ch'], '1')
            self.assertEqual(d['chapters'][1]['ch'], '2')
            self.assertEqual(d['chapters'][2]['ch'], '3')

    def test_detail_404(self):
        web, fake_get = _mock_web({'/series/non-exist': '<html><head><title>404 Not Found</title></head><body>No content</body></html>'})
        with patch.object(web, '_fetch', side_effect=lambda u, **kw: fake_get(u).text):
            d = web.detail('non-exist')
            self.assertIsNone(d)

    def test_chapter_images(self):
        web, fake_get = _mock_web({'/series/magic-emperor/chapter/1': CHAPTER_HTML})
        with patch.object(web, '_fetch', side_effect=lambda u, **kw: fake_get(u).text):
            imgs = web.chapter_images('vt-magic-emperor', '1')
            self.assertEqual(len(imgs), 3)
            self.assertEqual(imgs[0], 'https://cdn.voratoon.com/img/01.jpg')

    def test_chapter_images_empty(self):
        web, fake_get = _mock_web({'/series/magic-emperor/chapter/999': '<html><body>Empty</body></html>'})
        with patch.object(web, '_fetch', side_effect=lambda u, **kw: fake_get(u).text):
            imgs = web.chapter_images('magic-emperor', '999')
            self.assertEqual(imgs, [])


if __name__ == '__main__':
    unittest.main()
