import os
import tempfile
import unittest

from scraper.storage import FileStorage


class FileStorageTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = FileStorage(self.tmpdir)

    def test_save_exists_get_url(self):
        key = self.storage.key_from_url("https://example.com/a.jpg")
        url = self.storage.save(b"data", key)
        self.assertTrue(self.storage.exists(key))
        self.assertEqual(url, os.path.join(self.tmpdir, key))

    def test_key_is_safe_and_deterministic(self):
        k1 = FileStorage.key_from_url("https://example.com/../../etc/passwd")
        k2 = FileStorage.key_from_url("https://example.com/../../etc/passwd")
        self.assertEqual(k1, k2)
        self.assertTrue(k1.startswith("images/"))
        self.assertNotIn("..", k1)

    def test_delete(self):
        key = self.storage.key_from_url("https://example.com/x.jpg")
        self.storage.save(b"x", key)
        self.storage.delete(key)
        self.assertFalse(self.storage.exists(key))

    def test_get_url_with_base(self):
        storage = FileStorage(self.tmpdir, base_url="https://cdn.local")
        key = storage.key_from_url("https://example.com/x.jpg")
        self.assertTrue(storage.get_url(key).startswith("https://cdn.local/"))


if __name__ == "__main__":
    unittest.main()