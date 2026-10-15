import unittest
from unittest.mock import patch

from shinigami_web import ShinigamiWeb, _chapter_num

MANGA_UUID = "c0f1d049-ff7f-474d-8c6a-3a55e4c44147"
CHAP_UUID = "49f9e552-13f8-4c5f-a1a0-8f93261f57ca"

LIST_JSON = {
    "success": True,
    "data": {
        "mangas": [
            {"title": "Demonic Emperor",
             "thumbnail": "https://assets.shngm.id/thumb/a.jpg",
             "url": MANGA_UUID,
             "mangaUrl": f"https://app.shinigami.asia/series/{MANGA_UUID}"},
            {"title": "Nano Machine",
             "thumbnail": "https://assets.shngm.id/thumb/b.jpg",
             "url": "d3b05787-4c8e-42bb-ba9a-6b2fafd92f3c",
             "mangaUrl": "https://app.shinigami.asia/series/d3b05787"},
        ],
        "hasNextPage": True,
    },
}

DETAIL_JSON = {
    "success": True,
    "data": {
        "title": "Demonic Emperor",
        "author": "Wuer Manhua, Ye Xiao",
        "artist": "Wuer Manhua",
        "status": "Ongoing",
        "description": "Kaisar iblis terlahir kembali.",
        "genre": "Action, Adventure, Fantasy, Manhua",
        "thumbnail": "https://assets.shngm.id/thumb/a.jpg",
    },
}

CHAPTERS_JSON = {
    "success": True,
    "data": [
        {"name": "Chapter 2", "dateUpload": 1791593808000,
         "url": "uuid-ch-2",
         "chapterUrl": "https://app.shinigami.asia/series/x/uuid-ch-2"},
        {"name": "Chapter 1", "dateUpload": 1791507798000,
         "url": "uuid-ch-1",
         "chapterUrl": "https://app.shinigami.asia/series/x/uuid-ch-1"},
    ],
}

PAGES_JSON = {
    "success": True,
    "data": [
        {"index": 0, "imageUrl": "https://assets.shngm.id/chapter/m/00.jpg"},
        {"index": 1, "imageUrl": "https://assets.shngm.id/chapter/m/01.jpg"},
    ],
}


def _mock_client(mapping):
    """mapping: substring URL -> payload JSON / Exception."""
    web = ShinigamiWeb(base="http://mock/api")

    def fake_get_json(path, params=None, attempts=3):
        url = path + str(params or "")
        for k in sorted(mapping.keys(), key=len, reverse=True):
            if k in url:
                payload = mapping[k]
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise AssertionError(f"unexpected shinigami call: {url}")

    return web, fake_get_json


class TestShinigamiWeb(unittest.TestCase):
    def test_chapter_num(self):
        self.assertEqual(_chapter_num("Chapter 921"), "921")
        self.assertEqual(_chapter_num("Chapter 12 - Judul"), "12")
        self.assertEqual(_chapter_num("Chapter 7.5"), "7.5")
        self.assertEqual(_chapter_num("Prolog"), "")

    def test_latest(self):
        web, fake = _mock_client({"/manga/latest": LIST_JSON})
        with patch.object(web, "_get_json", side_effect=fake):
            items = web.latest(1)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["slug"], f"shn-{MANGA_UUID}")
            self.assertEqual(items[0]["title"], "Demonic Emperor")
            self.assertEqual(items[0]["source"], "shinigami")
            self.assertTrue(items[0]["cover"].startswith("https://"))

    def test_latest_gagal_kosong(self):
        import requests
        web, fake = _mock_client({"/manga/latest": requests.RequestException("down")})
        with patch.object(web, "_get_json", side_effect=fake):
            self.assertEqual(web.latest(1), [])

    def test_popular(self):
        web, fake = _mock_client({"/manga/popular": LIST_JSON})
        with patch.object(web, "_get_json", side_effect=fake):
            items = web.popular()
            self.assertEqual(len(items), 2)
            self.assertEqual(items[1]["slug"], "shn-d3b05787-4c8e-42bb-ba9a-6b2fafd92f3c")

    def test_search(self):
        web, fake = _mock_client({"/manga/search": LIST_JSON})
        with patch.object(web, "_get_json", side_effect=fake):
            res = web.search("demonic", 1)
            self.assertEqual(len(res["items"]), 2)
            self.assertEqual(res["query"], "demonic")
            self.assertTrue(res["has_next"])

    def test_search_kosong(self):
        web = ShinigamiWeb(base="http://mock/api")
        res = web.search("   ", 1)
        self.assertEqual(res["items"], [])

    def test_detail(self):
        web, fake = _mock_client({
            f"/manga/{MANGA_UUID}": DETAIL_JSON,
            f"/manga/{MANGA_UUID}/chapters": CHAPTERS_JSON,
        })
        with patch.object(web, "_get_json", side_effect=fake):
            d = web.detail(f"shn-{MANGA_UUID}")
            self.assertIsNotNone(d)
            self.assertEqual(d["title"], "Demonic Emperor")
            self.assertEqual(d["author"], "Wuer Manhua, Ye Xiao")
            self.assertEqual(d["status"], "Ongoing")
            self.assertEqual(d["source"], "shinigami")
            self.assertEqual(d["total_chapters"], 2)
            # terurut menaik: Chapter 1 dulu
            self.assertEqual(d["chapters"][0]["ch"], "1")
            self.assertEqual(d["chapters"][1]["ch"], "2")
            self.assertEqual(d["chapters"][0]["url"], f"/read/shn-{MANGA_UUID}/1")

    def test_chapter_images(self):
        web, fake = _mock_client({
            f"/manga/{MANGA_UUID}/chapters": CHAPTERS_JSON,
            "/manga/chapter/uuid-ch-1/pages": PAGES_JSON,
        })
        with patch.object(web, "_get_json", side_effect=fake):
            imgs = web.chapter_images(f"shn-{MANGA_UUID}", "1")
            self.assertEqual(len(imgs), 2)
            self.assertEqual(imgs[0], "https://assets.shngm.id/chapter/m/00.jpg")

    def test_chapter_images_tak_ketemu(self):
        web, fake = _mock_client({f"/manga/{MANGA_UUID}/chapters": CHAPTERS_JSON})
        with patch.object(web, "_get_json", side_effect=fake):
            self.assertEqual(web.chapter_images(f"shn-{MANGA_UUID}", "999"), [])


if __name__ == "__main__":
    unittest.main()
