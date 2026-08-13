import unittest
from unittest.mock import patch

from komiku_web import KomikuWeb

CARD_PAGE = """
<div class="page-info">(7,619 komik)</div>
<div class="manga-grid">
  <article class="manga-card">
    <a href="/manga/alpha-comic/">
      <img class="lazy" src="https://komiku.org/asset/img/lazy.jpg"
           data-src="https://thumbnail.komiku.org/img/a.jpg?resize=160,220&#038;quality=60" alt="Alpha">
    </a>
    <div><h4><a href="/manga/alpha-comic/"> Alpha Comic </a></h4>
      <p class="meta">Manhwa &bull; Drama<br>Status: Ongoing</p></div>
  </article>
  <article class="manga-card">
    <a href="/manga/beta-comic/">
      <img class="lazy" data-src="//thumbnail.komiku.org/img/b.jpg" alt="Beta">
    </a>
    <div><h4><a href="/manga/beta-comic/">Beta Comic</a></h4>
      <p class="meta">Manga &bull; Aksi<br>Status: End</p></div>
  </article>
  <article class="manga-card">
    <a href="/manga/alpha-comic/"><img data-src="https://thumbnail.komiku.org/img/a.jpg"></a>
    <div><h4><a href="/manga/alpha-comic/">Alpha Comic</a></h4></div>
  </article>
</div>
"""

BGE_PAGE = """
<div class="bge">
  <div class="bgei">
    <a href="/manga/gamma-comic/">
      <img src="https://thumbnail.komiku.org/img/g.jpg?resize=450,235&#038;quality=60" class="lazy">
      <div class="tpe1_inf"><b>Manhua</b> Romantis</div>
    </a>
  </div>
  <div class="kan">
    <a href="/manga/gamma-comic/"><h3>Gamma Comic</h3></a>
    <div class="new1"><a href="/x-chapter-1/"><span>Awal: </span><span>Chapter 1</span></a></div>
    <div class="new1"><a href="/x-chapter-42/"><span>Terbaru: </span><span>Chapter 42</span></a></div>
  </div>
</div>
"""

GENRE_PAGE = """
<a href="https://komiku.org/genre/action/">Action</a>
<a href="https://komiku.org/genre/dark-fantasy/">Dark Fantasy</a>
<a href="https://komiku.org/genre/action/">Action</a>
<a href="https://komiku.org/genre/apocalypse/">apocalypse</a>
"""


class CatalogParseTest(unittest.TestCase):
    def setUp(self):
        self.web = KomikuWeb()

    def fetch(self, body):
        return patch.object(KomikuWeb, "_fetch", return_value=body)

    def test_catalog_parses_cards_and_pagination(self):
        with self.fetch(CARD_PAGE):
            d = self.web.catalog(1)
        self.assertEqual(d["total"], 7619)
        self.assertEqual(d["total_pages"], 153)
        self.assertEqual(d["per_page"], 50)
        self.assertTrue(d["has_next"])
        self.assertEqual(len(d["items"]), 2, "duplikat slug harus dibuang")
        first = d["items"][0]
        self.assertEqual(first["slug"], "alpha-comic")
        self.assertEqual(first["title"], "Alpha Comic")
        self.assertEqual(first["type"], "Manhwa")
        self.assertEqual(first["genre"], "Drama")
        self.assertEqual(first["status"], "Ongoing")

    def test_catalog_skips_lazy_placeholder_and_unescapes_cover(self):
        with self.fetch(CARD_PAGE):
            items = self.web.catalog(1)["items"]
        self.assertNotIn("lazy.jpg", items[0]["cover"])
        self.assertIn("&quality=60", items[0]["cover"])
        self.assertTrue(items[1]["cover"].startswith("https://"), "// harus jadi https://")

    def test_catalog_last_page_has_no_next(self):
        with self.fetch(CARD_PAGE):
            self.assertFalse(self.web.catalog(153)["has_next"])

    def test_catalog_builds_filter_query(self):
        with patch.object(KomikuWeb, "_fetch", return_value=CARD_PAGE) as f:
            self.web.catalog(3, ctype="manhwa", letter="a")
        url = f.call_args[0][0]
        self.assertIn("halaman=3", url)
        self.assertIn("tipe=manhwa", url)
        self.assertIn("huruf=A", url)

    def test_catalog_rejects_unknown_type(self):
        with patch.object(KomikuWeb, "_fetch", return_value=CARD_PAGE) as f:
            self.web.catalog(1, ctype="bogus")
        self.assertNotIn("tipe=", f.call_args[0][0])

    def test_search_parses_listing(self):
        with self.fetch(BGE_PAGE):
            d = self.web.search("gamma", 2)
        self.assertEqual(d["page"], 2)
        self.assertEqual(len(d["items"]), 1)
        item = d["items"][0]
        self.assertEqual(item["slug"], "gamma-comic")
        self.assertEqual(item["title"], "Gamma Comic")
        self.assertEqual(item["type"], "Manhua")
        self.assertEqual(item["chapter"], "Chapter 42")
        self.assertFalse(d["has_next"], "kurang dari per_page berarti habis")

    def test_search_empty_query_short_circuits(self):
        with patch.object(KomikuWeb, "_fetch") as f:
            self.assertEqual(self.web.search("  ")["items"], [])
        f.assert_not_called()

    def test_genre_sanitizes_slug(self):
        with patch.object(KomikuWeb, "_fetch", return_value=BGE_PAGE) as f:
            self.web.by_genre("Action/../etc", 1)
        self.assertIn("genre=actionetc", f.call_args[0][0])

    def test_genres_dedupes_and_sorts(self):
        with self.fetch(GENRE_PAGE):
            g = self.web.genres()
        self.assertEqual([x["slug"] for x in g], ["action", "apocalypse", "dark-fantasy"])
        self.assertEqual(g[0]["name"], "Action")


if __name__ == "__main__":
    unittest.main()
