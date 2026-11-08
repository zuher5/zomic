import unittest
import requests
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

    def test_catalog_fallback_title_humanized(self):
        # Kartu tanpa <h4>: slug drain dulu ke '<h4>' tidak ada, judul harus
        # jadi 'Jungle Juice', bukan 'jungle-juice'.
        page = """
        <div class="page-info">(7,619 komik)</div>
        <div class="manga-grid">
          <article class="manga-card">
            <a href="/manga/jungle-juice/">
              <img class="lazy" data-src="https://thumbnail.komiku.org/img/j.jpg" alt="Jungle Juice">
            </a>
            <div><p class="meta">Manhua &bull; Action<br>Status: Ongoing</p></div>
          </article>
        </div>
        """
        with self.fetch(page):
            d = self.web.catalog(1)
        self.assertEqual(d["items"][0]["title"], "Jungle Juice")
        self.assertEqual(d["items"][0]["slug"], "jungle-juice")

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

    def test_search_fallback_title_humanized(self):
        # Blok .bge tanpa <h3>: tangkap slug-nya sebagai judul ramah.
        page = """
        <div class="bge">
          <div class="bgei">
            <a href="/manga/jungle-juice/">
              <img src="https://thumbnail.komiku.org/img/j.jpg" class="lazy">
              <div class="tpe1_inf"><b>Manhua</b> Action</div>
            </a>
          </div>
          <div class="kan">
            <div class="new1"><a href="/x-chapter-1/"><span>Terbaru: </span><span>Chapter 1</span></a></div>
          </div>
        </div>
        """
        with self.fetch(page):
            d = self.web.search("jungle", 1)
        self.assertEqual(d["items"][0]["title"], "Jungle Juice")

    def test_genre_sanitizes_slug(self):
        with patch.object(KomikuWeb, "_fetch", return_value=BGE_PAGE) as f:
            self.web.by_genre("Action/../etc", 1)
        self.assertIn("genre=actionetc", f.call_args[0][0])

    def test_genre_falls_back_to_alternate_endpoint(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if len(calls) == 1:
                raise requests.HTTPError('upstream 502')
            return BGE_PAGE
        with patch.object(KomikuWeb, "_fetch", side_effect=fetch):
            d = self.web.by_genre("action", 2)
        self.assertEqual(len(d["items"]), 1)
        self.assertIn("/genre/action/page/2/", calls[1])

    def test_genres_dedupes_and_sorts(self):
        with self.fetch(GENRE_PAGE):
            g = self.web.genres()
        self.assertEqual([x["slug"] for x in g], ["action", "apocalypse", "dark-fantasy"])
        self.assertEqual(g[0]["name"], "Action")

    def test_detail_parsing(self):
        # Di HTML komiku.org, chapter tampil descending (chapter terbaru di atas).
        # komiku_web.detail membalik urutan (reverse) agar ascending (Ch 1 ... Ch N)
        # seperti format standar API zomic.
        html = """
        <h1>Komik <span itemprop="name">Test Comic</span></h1>
        <div class="ims"><img src="https://thumbnail.komiku.to/img/test.jpg?w=500"></div>
        <table>
          <tr><td>Jenis Komik:</td><td>Manhwa</td></tr>
          <tr><td>Status:</td><td>Ongoing</td></tr>
          <tr><td>Pengarang:</td><td>Author A</td></tr>
        </table>
        <p itemprop="description">Sinopsis komik ini.</p>
        <ul class="genre">
          <li>Action</li><li>Comedy</li>
        </ul>
        <table>
          <tr>
            <td class="judulseries"><a href="/test-comic-chapter-2/"><span>Chapter 2</span></a></td>
            <td class="tanggalseries">02/01/2026</td>
          </tr>
          <tr>
            <td class="judulseries"><a href="/test-comic-chapter-1/"><span>Chapter 1</span></a></td>
            <td class="tanggalseries">01/01/2026</td>
          </tr>
        </table>
        """
        mock_resp = unittest.mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        with patch("komiku_web.retry_get", return_value=mock_resp):
            d = self.web.detail("test-comic")
        self.assertIsNotNone(d)
        self.assertEqual(d["title"], "Test Comic")
        self.assertEqual(d["cover"], "https://thumbnail.komiku.to/img/test.jpg")
        self.assertEqual(d["type"], "Manhwa")
        self.assertEqual(d["author"], "Author A")
        self.assertEqual(d["sinopsis"], "Sinopsis komik ini.")
        self.assertEqual(d["total_chapters"], 2)
        self.assertEqual(d["chapters"][0]["ch"], "1")
        self.assertEqual(d["chapters"][1]["ch"], "2")

    def test_chapter_parsing(self):
        html = """
        <div id="Baca_Komik">
          <img src="https://img.komiku.org/komiku-promosi.webp">
          <img src="https://img.komiku.org/upload/1.webp">
          <img src="https://img.komiku.org/upload/2.webp">
        </div>
        <div id="comment-section"></div>
        """
        mock_resp = unittest.mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        with patch("komiku_web.retry_get", return_value=mock_resp):
            imgs = self.web.chapter("test-comic", "1")
        self.assertEqual(imgs, [
            "https://img.komiku.org/upload/1.webp",
            "https://img.komiku.org/upload/2.webp"
        ])


if __name__ == "__main__":
    unittest.main()
