import re
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / 'web' / 'index.html').read_text(encoding='utf-8')


class ReaderUrlGuardTest(unittest.TestCase):
    """Reader hanya boleh memuat gambar http(s) dari API, sesuai aturan proxy."""

    def test_safe_http_url_helper_exists_and_is_strict(self):
        self.assertIn("const safeHttpUrl = u => (typeof u === 'string' && /^https?:\\/\\//i.test(u)) ? u : '';", HTML)

    def test_reader_template_never_puts_raw_url_in_data_src(self):
        # Jalur baca: data-src harus lewat safeHttpUrl, bukan u mentah.
        self.assertNotIn('data-src="${esc(u)}"', HTML)
        self.assertIn('data-src="${esc(safeHttpUrl(u))}"', HTML)

    def test_loader_skips_direct_src_when_url_is_unsafe(self):
        self.assertIn("if (img.dataset.src) img.src = img.dataset.src;", HTML)
        self.assertIn("else { onImgFail(img, slot); return; }", HTML)


if __name__ == '__main__':
    unittest.main()
