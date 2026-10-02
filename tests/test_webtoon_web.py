import unittest

from types import SimpleNamespace

from webtoon_web import (
    WebtoonWeb, _fix_cdn, _humanize_slug, _is_age_gate,
)


# Fixture disusun dari respons nyata webtoons.com (/id/, Feb 2026 probe).
CATALOG_HTML = '''
<html><body>
<a href="https://www.webtoons.com/id/romantic-fantasy/serena/list?title_no=5001">Serena</a>
<a href="/id/drama/the-fox-club/list?title_no=3616">The Fox Club</a>
<a href="/id/action/lout-of-the-counts-family/list?title_no=11151">Lout</a>
<!-- duplikat title_no yang sama, harus di-dedup -->
<a href="/id/romance/serena-again/list?title_no=5001">duplikat</a>
</body></html>
'''

DETAIL_HTML = '''
<html><head>
<link rel="canonical" href="https://www.webtoons.com/id/romantic-fantasy/serena/list?title_no=5001">
<meta property="og:image" content="https://webtoon-phinf.pstatic.net/cover_PNG/serena.jpg?type=q90">
<meta property="com-linewebtoon:webtoon:author" content="Yuu Nabata">
</head><body>
<h1 class="subj">Serena</h1>
<div id="_asideDetail"><p class="summary">  $
  Serena像一个...
  disimulasikan.</p></div>
<p class="day_info"> UP EVERY MONDAY </p>
<h2 class="genre">Romantic Fantasy</h2>
</body></html>
'''

EPISODES_JSON = {
    'success': True,
    'result': {
        'episodeList': [
            {'episodeNo': 1, 'episodeTitle': 'PROLOG',
             'viewerLink': '/id/romantic-fantasy/serena/prolog/viewer?title_no=5001&episode_no=1',
             'exposureDateMillis': 1670994041000, 'displayUp': True, 'hasBgm': False},
            {'episodeNo': 2, 'episodeTitle': 'EP 2',
             'viewerLink': '/id/romantic-fantasy/serena/ep2/viewer?title_no=5001&episode_no=2',
             'exposureDateMillis': 1671080441000, 'displayUp': True, 'hasBgm': True},
            # draft: exposureDateMillis <= 0 -> harus dibuang
            {'episodeNo': 3, 'episodeTitle': 'DRAFT',
             'viewerLink': '/x/viewer?episode_no=3',
             'exposureDateMillis': 0, 'displayUp': False, 'hasBgm': False},
        ],
        'nextCursor': None,
    },
}

# Halaman viewer nyata memuat ~335 data-url; hanya sebagian panel.
VIEWER_HTML = '''
<div id="_imageList">
  <img data-url="https://webtoon-phinf.pstatic.net/a_PNG/6id_warning.png?type=q90" class="_images">
  <img data-url="https://webtoon-phinf.pstatic.net/b_PNG/thumb_167082270846_Serena_01.jpg" class="_images">
  <img data-url="https://webtoon-phinf.pstatic.net/c_PNG/1670841989803_Serena_01_01_01.jpg?type=q90" class="_images">
  <img data-url="https://webtoon-phinf.pstatic.net/d_PNG/1670841989804_Serena_01_02_01.jpg" class="_images">
  <img data-url="https://webtoon-phinf.pstatic.net/e_PNG/site_logo.png" class="_images">
  <img data-url="https://webtoon-phinf.pstatic.net/f_PNG/thumb_167082270847_Serena_02.jpg" class="_images">
  <img data-url="https://webtoon-phinf.pstatic.net/g_PNG/1670841989805_Serena_01_03_01.jpg" class="_images">
</div>
'''


def _web(mapping):
    """Bangun WebtoonWeb tanpa jaringan; _fetch mengembalikan fixture."""
    web = WebtoonWeb.__new__(WebtoonWeb)
    web.timeout = 5

    def mock_fetch(url, **kwargs):
        for frag, payload in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
            if frag in url:
                if isinstance(payload, dict):
                    return SimpleNamespace(text='', url=url, json=lambda p=payload: p)
                return SimpleNamespace(text=payload, url=url,
                                       json=lambda: (_ for _ in ()).throw(
                                           ValueError('bukan json')))
        raise AssertionError(f'fixture tidak ada untuk: {url}')
    web._fetch = mock_fetch
    return web


class TestHelpers(unittest.TestCase):
    def test_humanize_slug(self):
        self.assertEqual(_humanize_slug('how-to-win-my-husband-over'),
                         'How To Win My Husband Over')

    def test_fix_cdn_rewrites_host_and_strips_quality(self):
        got = _fix_cdn('https://webtoon-phinf.pstatic.net/x_PNG/a.jpg?type=q90')
        self.assertTrue(got.startswith('https://swebtoon-phinf.pstatic.net/'))
        self.assertNotIn('type=q90', got)

    def test_fix_cdn_preserves_other_query(self):
        got = _fix_cdn('https://webtoon-phinf.pstatic.net/a.jpg?foo=1&type=q50')
        self.assertIn('foo=1', got)
        self.assertNotIn('type=q', got)

    def test_fix_cdn_handles_none(self):
        self.assertIsNone(_fix_cdn(None))

    def test_is_age_gate_detects_text_marker(self):
        class R:
            url = 'https://www.webtoons.com/id/x/list'
        self.assertTrue(_is_age_gate(R(), 'Please Verify your age to continue'))
        self.assertFalse(_is_age_gate(R(), '<html>normal</html>'))

    def test_is_age_gate_detects_redirect(self):
        class R:
            url = 'https://www.webtoons.com/ageGate'
        self.assertTrue(_is_age_gate(R(), '<html>x</html>'))


class TestKindFromUrl(unittest.TestCase):
    def test_canvas_detected(self):
        self.assertEqual(WebtoonWeb._kind_from_url(
            '/id/canvas/serena/list?title_no=5001'), 'canvas')

    def test_regular_is_webtoon(self):
        self.assertEqual(WebtoonWeb._kind_from_url(
            '/id/romantic-fantasy/serena/list?title_no=5001'), 'webtoon')


class TestParseCards(unittest.TestCase):
    def test_parse_cards_extracts_and_dedupes(self):
        cards = WebtoonWeb._parse_cards(CATALOG_HTML)
        self.assertEqual(len(cards), 3)
        self.assertEqual({c['title_no'] for c in cards}, {5001, 3616, 11151})
        self.assertTrue(all(c['type'] == 'webtoon' for c in cards))
        self.assertEqual(cards[0]['slug'], 'serena')

    def test_parse_cards_respects_limit(self):
        self.assertEqual(len(WebtoonWeb._parse_cards(CATALOG_HTML, limit=2)), 2)

    def test_parse_cards_empty(self):
        self.assertEqual(WebtoonWeb._parse_cards('<html></html>'), [])

    def test_home_and_genres_use_fixture(self):
        web = _web({'/id/': CATALOG_HTML})
        self.assertTrue(web.home(1))
        g = web.genres()
        slugs = {x['slug'] for x in g}
        self.assertIn('romantic-fantasy', slugs)
        self.assertNotIn('canvas', slugs)


class TestDetail(unittest.TestCase):
    def test_detail_builds_url_from_genre_and_slug(self):
        seen = {}
        web = _web({'list?title_no=5001': DETAIL_HTML})
        base = web._fetch
        def spy(url, **kw):
            seen['url'] = url
            return base(url, **kw)
        web._fetch = spy
        web.detail(5001, genre='romantic-fantasy', slug='serena')
        self.assertIn('/id/romantic-fantasy/serena/list?title_no=5001', seen['url'])

    def test_detail_resolves_from_catalog_when_no_genre(self):
        web = _web({'/id/': CATALOG_HTML, 'list?title_no=5001': DETAIL_HTML})
        # title_no 5001 ada di CATALOG_HTML sebagai /id/romantic-fantasy/serena/
        d = web.detail(5001)
        self.assertEqual(d['title_no'], 5001)

    def test_detail_parses_metadata(self):
        web = _web({'list?title_no=5001': DETAIL_HTML})
        d = web.detail(5001, 'romantic-fantasy', 'serena')
        self.assertEqual(d['title'], 'Serena')
        self.assertEqual(d['author'], 'Yuu Nabata')
        self.assertEqual(d['title_no'], 5001)
        self.assertEqual(d['type'], 'webtoon')
        self.assertEqual(d['genre'], 'Romantic Fantasy')
        self.assertEqual(d['status'], 'ongoing')
        self.assertIn('serena.jpg', d['cover'])
        self.assertTrue(d['cover'].startswith('https://swebtoon-phinf'))

    def test_detail_status_completed(self):
        html = DETAIL_HTML.replace('UP EVERY MONDAY', 'END')
        web = _web({'list?title_no=5001': html})
        self.assertEqual(web.detail(5001, 'romantic-fantasy', 'serena')['status'], 'completed')

    def test_detail_uses_canonical_title_no(self):
        web = _web({'list?title_no=5001': DETAIL_HTML})
        # canonical menunjuk 5001; argumen genre/slug menghasilkan URL yg cocok
        self.assertEqual(web.detail(5001, 'romantic-fantasy', 'serena')['title_no'], 5001)

    def test_detail_returns_none_on_error_or_missing(self):
        web = _web({'list?title_no=9999': '<html><head><title>Connect Error :: WEBTOON</title></head><body>Error</body></html>'})
        self.assertIsNone(web.detail(9999))
        web2 = _web({'list?title_no=9999': '<html><body><div>No content</div></body></html>'})
        self.assertIsNone(web2.detail(9999))


class TestEpisodes(unittest.TestCase):
    def test_episodes_parses_and_sorts(self):
        web = _web({'m.webtoons.com/api': EPISODES_JSON})
        eps = web.episodes(5001)
        self.assertEqual([e['chapter'] for e in eps], ['1', '2'])
        self.assertEqual(eps[0]['title'], 'PROLOG')
        self.assertTrue(eps[0]['url'].startswith('https://www.webtoons.com/id/'))
        self.assertFalse(eps[0]['has_bgm'])
        self.assertTrue(eps[1]['has_bgm'])

    def test_episodes_drops_unpublished_draft(self):
        web = _web({'m.webtoons.com/api': EPISODES_JSON})
        titles = [e['title'] for e in web.episodes(5001)]
        self.assertNotIn('DRAFT', titles)

    def test_episodes_empty_on_bad_payload(self):
        web = _web({'m.webtoons.com/api': {'result': {}}})
        self.assertEqual(web.episodes(5001), [])

    def test_episodes_uses_kind_in_url(self):
        web = _web({'canvas/5001': EPISODES_JSON})
        self.assertTrue(web.episodes(5001, kind='canvas'))


class TestChapterImages(unittest.TestCase):
    def test_only_real_panels_returned(self):
        web = _web({'viewer': VIEWER_HTML})
        imgs = web.chapter_images('https://www.webtoons.com/id/x/viewer?title_no=5001&episode_no=1')
        # 7 data-url di fixture: 1 warning + 2 thumb + 1 logo dibuang -> 3 panel
        self.assertEqual(len(imgs), 3)
        self.assertTrue(all('thumb_' not in i for i in imgs))
        self.assertTrue(all('warning' not in i for i in imgs))
        self.assertTrue(all('logo' not in i for i in imgs))

    def test_cdn_fixed_and_deduped(self):
        web = _web({'viewer': VIEWER_HTML})
        imgs = web.chapter_images('https://www.webtoons.com/id/x/viewer')
        self.assertTrue(all(i.startswith('https://swebtoon-phinf.') for i in imgs))
        self.assertTrue(all('type=q' not in i for i in imgs))
        self.assertEqual(len(imgs), len(set(imgs)))

    def test_empty_on_age_gate(self):
        web = _web({'viewer': '<html>Please Verify your age</html>'})
        self.assertEqual(web.chapter_images('https://www.webtoons.com/id/x/viewer'), [])

    def test_no_url_returns_empty(self):
        web = _web({})
        self.assertEqual(web.chapter_images(None), [])

    def test_chapter_images_canvas_fallback(self):
        web = _web({
            'webtoon/777/episodes': {'result': {'episodeList': []}},
            'canvas/777/episodes': EPISODES_JSON,
            'viewer': VIEWER_HTML,
        })
        imgs = web.chapter_images(777, '1')
        self.assertEqual(len(imgs), 3)


if __name__ == '__main__':
    unittest.main()