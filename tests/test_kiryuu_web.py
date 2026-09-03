"""Unit tests untuk kiryuu_web.py — parsing HTML kiryuu.to."""

import json
import unittest

from kiryuu_web import KiryuuWeb, _clean_chapter_num, _clean_slug, _text


# ---------- HTML FIXTURES ----------

HOME_CARD_HTML = '''
<div class="flex flex-col h-[240px]">
  <a color="primary" class="w-full h-full" href="https://v7.kiryuu.to/manga/martial-peak/">
    <div class="w-full h-full">
      <img width="320" height="477" src="https://v7.kiryuu.to/wp-content/uploads/2021/03/Martial-Peak.jpg"
           class="h-full object-cover wp-post-image" alt="Martial Peak" loading="lazy" />
    </div>
  </a>
  <span class="absolute right-[2px] top-[2px]">
    <img src="https://v7.kiryuu.to/wp-content/themes/kiryuu/static/svg/manhua.svg" alt="manhua" />
  </span>
  <div class="flex justify-between mx-2 my-2">
    <div class="flex items-center gap-1">
      <div class="numscore">7.60</div>
    </div>
    <div class="flex items-center gap-1">
      <span class="h-[10px] w-[10px] rounded-full inline-block relative bg-green-600"></span>
      <p class="font-normal text-xs">Ongoing</p>
    </div>
  </div>
  <div class="flex justify-center items-center h-[50px]">
    <a href="https://v7.kiryuu.to/manga/martial-peak/">
      <h1 class="text-[15px] font-bold text-center line-clamp-2 capitalize">
        Martial Peak
      </h1>
    </a>
  </div>
  <a href="https://v7.kiryuu.to/manga/martial-peak/chapter-3862.698726/">
    <div class="flex justify-center">
      <p class="inline-block">Chapter 3862</p>
    </div>
    <div class="flex justify-between text-[60%] text-gray-400">
      <time datetime="2025-12-24T07:53:28Z">8 months ago</time>
    </div>
  </a>
  <a href="https://v7.kiryuu.to/manga/martial-peak/chapter-3861.698539/">
    <div class="flex justify-center">
      <p class="inline-block">Chapter 3861</p>
    </div>
  </a>
</div>
'''

SEARCH_PAGE_HTML = '''
<html><body>
<div class="listupd">
<div class="bsx">
  <a href="https://v7.kiryuu.to/manga/solo-leveling/">
    <img src="https://v7.kiryuu.to/wp-content/uploads/2021/06/solo-leveling.jpg"
         class="wp-post-image" alt="Solo Leveling" />
  </a>
  <h4 class="line-clamp-2">Solo Leveling</h4>
  <div class="numscore">9.00</div>
</div>
<div class="bsx">
  <a href="https://v7.kiryuu.to/manga/eleceed/">
    <img src="https://v7.kiryuu.to/wp-content/uploads/2021/03/eleceed.jpg"
         class="wp-post-image" alt="Eleceed" />
  </a>
  <h4 class="line-clamp-2">Eleceed</h4>
</div>
</div>
<a href="https://v7.kiryuu.to/page/2/?s=test" class="next">Next</a>
</body></html>
'''

DETAIL_PAGE_HTML = '''
<html><body>
<script type="application/ld+json">{
    "@context": "https://schema.org",
    "@type": ["Book", "ComicSeries"],
    "@id": "https://v7.kiryuu.to/manga/martial-peak/#comicseries",
    "url": "https://v7.kiryuu.to/manga/martial-peak/",
    "name": "Martial Peak",
    "headline": "Martial Peak",
    "description": "Perjalanan ke puncak bela diri adalah yang sepi [&hellip;]",
    "inLanguage": "id_ID",
    "image": {
        "@type": "ImageObject",
        "url": "https://v7.kiryuu.to/wp-content/uploads/2021/03/Martial-Peak.jpg"
    },
    "author": { "@type": "Person", "name": "Momo (III)" },
    "genre": ["Action","Adventure","Comedy","Fantasy","Harem","Historical","Martial Arts","Romance","Sci-fi","Shounen","Supernatural"],
    "creativeWorkStatus": "Manhua",
    "isCompleted": false,
    "numberOfPages": 3870,
    "aggregateRating": {
        "@type": "AggregateRating",
        "ratingValue": 7.6,
        "bestRating": 10,
        "worstRating": 1
    },
    "alternateName": ["Vo Luyen Dinh Phong", "Wu Lian Dian Feng"]
}</script>

<h1 itemprop="name">Martial Peak</h1>

<div id="chapter-list">
  <div data-chapter-number="3862" class="flex flex-1 border rounded-md">
    <a href="https://v7.kiryuu.to/manga/martial-peak/chapter-3862.698726/" class="w-full">
      <span>Chapter 3862</span>
      <time datetime="2025-12-24T07:53:28Z">8 months ago</time>
    </a>
  </div>
  <div data-chapter-number="3861" class="flex flex-1 border rounded-md">
    <a href="https://v7.kiryuu.to/manga/martial-peak/chapter-3861.698539/" class="w-full">
      <span>Chapter 3861</span>
      <time datetime="2025-12-23T05:20:15Z">8 months ago</time>
    </a>
  </div>
  <div data-chapter-number="3860" class="flex flex-1 border rounded-md">
    <a href="https://v7.kiryuu.to/manga/martial-peak/chapter-3860.698530/" class="w-full">
      <span>Chapter 3860</span>
      <time datetime="2025-12-22T03:10:00Z">8 months ago</time>
    </a>
  </div>
</div>

<div itemprop="genre" href="https://v7.kiryuu.to/genre/action/">Action</div>
<a itemprop="genre" href="https://v7.kiryuu.to/genre/action/">
  <span>Action</span>
</a>
<a itemprop="genre" href="https://v7.kiryuu.to/genre/fantasy/">
  <span>Fantasy</span>
</a>
</body></html>
'''

CHAPTER_PAGE_HTML = '''
<html><body>
<section class="w-full flex flex-col justify-center items-center text-accent"
          data-image-data="1" oncontextmenu="return false;">
    <img src='https://yuucdn.com/wp-content/uploads/images/m/martial-peak/chapter-3862/1-694b9bc4b6f43.webp'>
    <img src='https://yuucdn.com/wp-content/uploads/images/m/martial-peak/chapter-3862/2-694b9bc6df75d.webp'>
    <img src='https://yuucdn.com/wp-content/uploads/images/m/martial-peak/chapter-3862/3-694b9bc8ec662.webp'>
</section>
</body></html>
'''

GENRE_JSON_SCRIPT = '''
<script>
var searchTerms = {"genre":[
  {"term_id":2,"name":"Action","slug":"action","taxonomy":"genre","count":4543},
  {"term_id":3,"name":"Adventure","slug":"adventure","taxonomy":"genre","count":2494},
  {"term_id":128,"name":"Adult","slug":"adult","taxonomy":"genre","count":166}
],"artist":[]}
</script>
'''

PAGINATION_HTML = '''
<div class="flex items-center gap-2">
  <a href="https://v7.kiryuu.to/?page=1&pagedfor=project" class="bg-accent">1</a>
  <a href="https://v7.kiryuu.to/?page=2&pagedfor=project">2</a>
  <a href="https://v7.kiryuu.to/?page=3&pagedfor=project">3</a>
</div>
'''


class TestHelpers(unittest.TestCase):
    def test_text(self):
        self.assertEqual(_text('  Hello  World  '), 'Hello World')
        self.assertEqual(_text('<b>Bold</b>'), 'Bold')
        self.assertEqual(_text(''), '')
        self.assertEqual(_text(None), '')

    def test_clean_slug(self):
        self.assertEqual(_clean_slug('https://v7.kiryuu.to/manga/martial-peak/'), 'martial-peak')
        self.assertEqual(_clean_slug('/manga/solo-leveling/'), 'solo-leveling')
        self.assertEqual(_clean_slug(''), '')
        self.assertEqual(_clean_slug(None), '')

    def test_clean_chapter_num(self):
        self.assertEqual(_clean_chapter_num('3862'), '3862')
        self.assertEqual(_clean_chapter_num('3862.698726'), '3862')
        self.assertEqual(_clean_chapter_num('12.5'), '12.5')
        self.assertEqual(_clean_chapter_num('12-5'), '12-5')
        self.assertEqual(_clean_chapter_num(''), '')


class TestParseCard(unittest.TestCase):
    def test_parse_card_from_block(self):
        card = KiryuuWeb._parse_card_from_block(HOME_CARD_HTML)
        self.assertIsNotNone(card)
        self.assertEqual(card['slug'], 'martial-peak')
        self.assertEqual(card['title'], 'Martial Peak')
        self.assertIn('Martial-Peak.jpg', card['cover'])
        self.assertEqual(card['type'], 'Manhua')
        self.assertEqual(card['rating'], '7.60')
        self.assertEqual(card['status'], 'Ongoing')
        self.assertEqual(card['chapter'], '3862')

    def test_parse_card_no_match(self):
        card = KiryuuWeb._parse_card_from_block('<div>nothing here</div>')
        self.assertIsNone(card)

    def test_parse_card_missing_cover(self):
        html = '''
        <a href="https://v7.kiryuu.to/manga/test-slug/">
        </a>
        <h1 class="line-clamp-2">Test Title</h1>
        '''
        card = KiryuuWeb._parse_card_from_block(html)
        self.assertIsNotNone(card)
        self.assertEqual(card['slug'], 'test-slug')
        self.assertEqual(card['cover'], '')


class TestParseListing(unittest.TestCase):
    def test_parse_home_page(self):
        items = KiryuuWeb._parse_listing(HOME_CARD_HTML)
        self.assertGreaterEqual(len(items), 1)
        slugs = [i['slug'] for i in items]
        self.assertIn('martial-peak', slugs)

    def test_parse_listing_dedupes(self):
        items = KiryuuWeb._parse_listing(HOME_CARD_HTML + HOME_CARD_HTML)
        slugs = [i['slug'] for i in items]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_parse_listing_empty_page(self):
        items = KiryuuWeb._parse_listing('<html><body>empty</body></html>')
        self.assertEqual(items, [])


class TestDetail(unittest.TestCase):
    def test_detail_parses_jsonld(self):
        web = KiryuuWeb.__new__(KiryuuWeb)
        web.timeout = 5
        web._local = type('', (), {'session': None})()

        # Monkey-patch _fetch
        original_fetch = web._fetch
        def mock_fetch(url, **kwargs):
            if '/manga/martial-peak/' in url:
                return DETAIL_PAGE_HTML
            return original_fetch(url, **kwargs)
        web._fetch = mock_fetch

        d = web.detail('martial-peak')
        self.assertEqual(d['title'], 'Martial Peak')
        self.assertEqual(d['slug'], 'martial-peak')
        self.assertIn('Martial-Peak.jpg', d['cover'])
        self.assertEqual(d['author'], 'Momo (III)')
        self.assertEqual(d['type'], 'Manhua')
        self.assertIn('Action', d['genre'])
        self.assertIn('Fantasy', d['genre'])
        self.assertIn('Perjalanan', d['sinopsis'])
        self.assertEqual(d['rating'], '7.6')
        self.assertEqual(len(d['chapters']), 3)
        self.assertEqual(d['chapters'][0]['ch'], '3860')
        self.assertEqual(d['chapters'][1]['ch'], '3861')
        self.assertEqual(d['chapters'][2]['ch'], '3862')

    def test_detail_alt_names(self):
        web = KiryuuWeb.__new__(KiryuuWeb)
        web.timeout = 5
        web._local = type('', (), {'session': None})()
        original_fetch = web._fetch
        def mock_fetch(url, **kwargs):
            return DETAIL_PAGE_HTML
        web._fetch = mock_fetch

        d = web.detail('martial-peak')
        self.assertIn('Vo Luyen Dinh Phong', d['alt_title'])

    def test_detail_sinopsis_cleans_hellip(self):
        web = KiryuuWeb.__new__(KiryuuWeb)
        web.timeout = 5
        web._local = type('', (), {'session': None})()
        def mock_fetch(url, **kwargs):
            return DETAIL_PAGE_HTML
        web._fetch = mock_fetch

        d = web.detail('martial-peak')
        self.assertNotIn('[&hellip;]', d['sinopsis'])


class TestChapterImages(unittest.TestCase):
    def test_parse_chapter_images(self):
        import re
        section_m = re.search(r'<section[^>]*data-image-data="1"[^>]*>(.*?)</section>', CHAPTER_PAGE_HTML, re.S)
        self.assertIsNotNone(section_m)
        imgs = re.findall(r"""src=['"]?(https://yuucdn\.com/[^'">\s]+)['"]?""", section_m.group(1), re.I)
        self.assertEqual(len(imgs), 3)
        self.assertTrue(all('yuucdn.com' in u for u in imgs))
        self.assertTrue(imgs[0].endswith('.webp'))


class TestGenres(unittest.TestCase):
    def test_parse_genres_from_json(self):
        web = KiryuuWeb()
        # Patch the _fetch method on the instance
        orig = web._fetch
        web._fetch = lambda url, **kwargs: GENRE_JSON_SCRIPT
        try:
            genres = web.genres()
        finally:
            web._fetch = orig

        self.assertGreater(len(genres), 0)
        slugs = [g['slug'] for g in genres]
        self.assertIn('action', slugs)
        self.assertIn('adventure', slugs)


class TestDedupe(unittest.TestCase):
    def test_dedupe_preserves_order(self):
        items = [
            {'slug': 'a', 'title': 'A'},
            {'slug': 'b', 'title': 'B'},
            {'slug': 'a', 'title': 'A-dup'},
        ]
        result = KiryuuWeb._dedupe(items)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['slug'], 'a')
        self.assertEqual(result[1]['slug'], 'b')

    def test_dedupe_empty(self):
        self.assertEqual(KiryuuWeb._dedupe([]), [])


if __name__ == '__main__':
    unittest.main()
