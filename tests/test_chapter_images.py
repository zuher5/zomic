import unittest

from app import KomikuAPI


class ChapterImageExtractionTest(unittest.TestCase):
    def setUp(self):
        self.api = KomikuAPI()

    def test_returns_all_images_not_just_first(self):
        payload = {"images": [{"src": f"https://img/{i}.webp", "id": str(i)} for i in range(1, 30)]}
        result = self.api._extract_images(payload)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 29)
        self.assertEqual(result[0], "https://img/1.webp")
        self.assertEqual(result[-1], "https://img/29.webp")

    def test_sorts_numerically_by_id(self):
        payload = {"images": [
            {"src": "https://img/10.webp", "id": "10"},
            {"src": "https://img/2.webp", "id": "2"},
            {"src": "https://img/1.webp", "id": "1"},
        ]}
        self.assertEqual(
            self.api._extract_images(payload),
            ["https://img/1.webp", "https://img/2.webp", "https://img/10.webp"],
        )

    def test_accepts_plain_list_of_strings(self):
        payload = ["https://img/1.jpg", "https://img/2.jpg"]
        self.assertEqual(self.api._extract_images(payload), payload)

    def test_accepts_alternate_container_keys(self):
        for key in ("images", "chapterImages", "pages", "chapter_images", "data"):
            with self.subTest(key=key):
                result = self.api._extract_images({key: ["https://img/1.jpg", "https://img/2.jpg"]})
                self.assertEqual(len(result), 2)

    def test_normalizes_protocol_relative_and_uses_fallback(self):
        payload = {"images": [{"src": "//img/1.jpg"}, {"fallbackSrc": "https://cdn/2.jpg"}]}
        self.assertEqual(self.api._extract_images(payload), ["https://img/1.jpg", "https://cdn/2.jpg"])

    def test_drops_duplicates_blanks_and_non_http_schemes(self):
        payload = {"images": [
            {"src": "https://img/1.jpg"},
            {"src": "https://img/1.jpg"},
            {"src": ""},
            {"src": "javascript:alert(1)"},
            None,
            {"src": "https://img/2.jpg"},
        ]}
        self.assertEqual(self.api._extract_images(payload), ["https://img/1.jpg", "https://img/2.jpg"])

    def test_empty_payload_returns_empty_list(self):
        self.assertEqual(self.api._extract_images({"images": []}), [])
        self.assertEqual(self.api._extract_images({}), [])
        self.assertEqual(self.api._extract_images(None), [])


if __name__ == "__main__":
    unittest.main()
