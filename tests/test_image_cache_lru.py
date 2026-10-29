import os
import tempfile
import time
import unittest
from unittest.mock import patch

import app as app_module


class ImageCacheLruTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        p = patch.object(app_module, 'IMAGE_CACHE_DIR', self.dir)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def _write(self, name, size, mtime):
        path = os.path.join(self.dir, name)
        with open(path, 'wb') as fh:
            fh.write(b'x' * size)
        os.utime(path, (mtime, mtime))
        return path

    def test_hit_refreshes_mtime_so_hot_entry_survives_eviction(self):
        now = time.time()
        hot = self._write('hot', 100, now - 1000)   # paling tua, tapi sering dipakai
        cold = self._write('cold', 100, now - 500)
        app_module._img_cache_get('hot', ttl=10**9)  # hit -> mtime diperbarui
        before = os.path.getmtime(hot)
        self.assertGreater(before, now - 10)
        with patch.object(app_module, 'IMAGE_CACHE_MAX_BYTES', 150):
            app_module._img_evict()
        self.assertTrue(os.path.exists(hot), 'entry yang baru dipakai harus bertahan')
        self.assertFalse(os.path.exists(cold), 'entry yang tidak dipakai harus dibuang')

    def test_evict_removes_stale_tmp_files_only(self):
        now = time.time()
        stale = self._write('abc.tmp123.456', 10, now - 3600)
        fresh = self._write('def.tmp999.1', 10, now - 5)
        keep = self._write('normal', 10, now - 3600)
        app_module._img_evict()
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(fresh))
        self.assertTrue(os.path.exists(keep))


if __name__ == '__main__':
    unittest.main()
