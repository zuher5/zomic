import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / 'web' / 'index.html').read_text(encoding='utf-8')


class InlineHandlerTest(unittest.TestCase):
    """Tidak boleh ada atribut on* inline untuk gambar; CSP script-src masih
    'unsafe-inline' sampai <script> inline dipindah (tindak lanjut terpisah)."""

    def test_no_inline_onerror_attributes(self):
        self.assertNotIn('onerror="', HTML)

    def test_cover_error_handled_by_delegated_listener(self):
        self.assertIn("document.addEventListener('error'", HTML)
        self.assertIn("hasAttribute('data-cover')", HTML)


if __name__ == '__main__':
    unittest.main()
