import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

# Sengaja TIDAK 'from app import app, cache': tests/test_img_proxy.py melakukan
# importlib.reload(app), sehingga binding lama jadi basi (cache lama dibersihkan
# sementara endpoint memakai cache baru). Selalu akses lewat modul.
import app as app_module

# Basis waktu stabil untuk window rotasi (kelipatan REC_ROTATE_SECONDS).
_T0 = 1_790_000_000 - (1_790_000_000 % app_module.REC_ROTATE_SECONDS)


def _card(slug, title, src):
    return {
        'slug': slug,
        'title': title,
        'cover': 'https://img.komiku.org/x.jpg',
        'type': 'Manga',
        'genre': 'Action',
        'chapter': '1',
        'source': src,
    }


def _pool(n, tag):
    return [_card(f'{tag}-{i}', f'{tag} Judul {i}', tag) for i in range(n)]


class RecommendedRotationTest(unittest.TestCase):
    """Recommended harus mengambil beberapa sumber dan dirotasi berkala."""

    def setUp(self):
        # Import app memicu lifespan -> prewarm sungguhan (api.latest) di thread
        # daemon yang bisa mencemari cache. Isolasi: cache & rate-limit bersih
        # dan wait api.latest dibuat no-op (test wajib tanpa jaringan).
        patcher = patch.object(app_module.api, 'latest', side_effect=lambda *_a, **_k: [])
        patcher.start()
        self.addCleanup(patcher.stop)
        app_module.cache.clear()
        app_module._RATE_BUCKETS.clear()
        self.addCleanup(app_module._RATE_BUCKETS.clear)
        self.addCleanup(app_module.cache.clear)
        self.client = TestClient(app_module.app)

    def _patch_upstreams(self, komiku=None, kiryuu=None, vora=None, shn=None):
        """Patch keempat upstream jadi data mock (tanpa jaringan)."""

        def _komiku():
            if isinstance(komiku, Exception):
                raise komiku
            return list(komiku or [])

        def _kiryuu_home(page=1):
            if isinstance(kiryuu, Exception):
                raise kiryuu
            return {'items': list(kiryuu or [])}

        def _vora():
            if isinstance(vora, Exception):
                raise vora
            return list(vora or [])

        def _shn():
            if isinstance(shn, Exception):
                raise shn
            return list(shn or [])

        ctxs = (
            patch.object(app_module.api, 'recommended', side_effect=_komiku),
            patch.object(app_module.kiryuu, 'home', side_effect=_kiryuu_home),
            patch.object(app_module.voratoon, 'popular', side_effect=_vora),
            patch.object(app_module.shinigami, 'popular', side_effect=_shn),
        )
        for c in ctxs:
            c.start()
            self.addCleanup(c.stop)

    def _get(self, at=None, **kw):
        self._patch_upstreams(**kw)
        app_module.cache.clear()
        if at is None:
            res = self.client.get('/api/recommended')
        else:
            with patch.object(app_module.time, 'time', return_value=at):
                res = self.client.get('/api/recommended')
        return res

    def test_kirim_dari_keempat_sumber(self):
        res = self._get(
            at=_T0,
            komiku=_pool(5, 'komiku'),
            kiryuu=_pool(5, 'kiryuu'),
            vora=_pool(5, 'vt'),
            shn=_pool(5, 'shn'),
        )
        self.assertEqual(res.status_code, 200, res.text)
        sources = {c.get('source') for c in res.json()}
        self.assertEqual(sources, {'komiku', 'kiryuu', 'voratoon', 'shinigami'})

    def test_rotasi_berganti_seiring_waktu(self):
        # Satu run: pool di-cache, waktu bergeser per window -> urutan berubah.
        self._patch_upstreams(
            komiku=_pool(8, 'komiku'),
            kiryuu=_pool(8, 'kiryuu'),
            vora=_pool(8, 'vt'),
            shn=_pool(8, 'shn'),
        )
        app_module.cache.clear()
        seen = []
        for step in range(4):
            with patch.object(app_module.time, 'time',
                              return_value=_T0 + step * app_module.REC_ROTATE_SECONDS):
                res = self.client.get('/api/recommended')
            self.assertEqual(res.status_code, 200, res.text)
            items = res.json()
            self.assertEqual(len(items), app_module.REC_LIMIT)
            seen.append(tuple(c['slug'] for c in items))

        self.assertGreater(len(set(seen)), 1, 'recommended tidak pernah berubah')
        leads = {s[0].split('-')[0] for s in seen}
        self.assertEqual(len(leads), 4, f'sumber terdepan tidak bergilir: {leads}')

    def test_rotasi_deterministik_per_window(self):
        self._patch_upstreams(
            komiku=_pool(6, 'komiku'),
            kiryuu=_pool(6, 'kiryuu'),
            vora=_pool(6, 'vt'),
            shn=_pool(6, 'shn'),
        )
        app_module.cache.clear()
        out = []
        for _ in range(2):
            with patch.object(app_module.time, 'time', return_value=_T0 + 60):
                out.append([c['slug'] for c in self.client.get('/api/recommended').json()])
        self.assertEqual(out[0], out[1])

    def test_satu_sumber_gagal_tetap_terisi(self):
        res = self._get(
            at=_T0,
            komiku=RuntimeError('boom'),
            kiryuu=_pool(5, 'kiryuu'),
            vora=RuntimeError('down'),
            shn=_pool(5, 'shn'),
        )
        self.assertEqual(res.status_code, 200, res.text)
        items = res.json()
        self.assertTrue(items)
        self.assertEqual({c['source'] for c in items}, {'kiryuu', 'shinigami'})

    def test_pool_datar_tidak_duplikat(self):
        res = self._get(
            at=_T0,
            komiku=_pool(3, 'komiku'),
            kiryuu=_pool(3, 'kiryuu'),
            vora=[_card('komiku-0', 'Komiku Judul 0', 'voratoon')],
            shn=[],
        )
        self.assertEqual(res.status_code, 200, res.text)
        slugs = [c['slug'] for c in res.json()]
        self.assertEqual(len(slugs), len(set(slugs)))
        # 3 komiku + 3 kiryuu (satu item voratoon duplikat dibuang),
        # shinigami kosong -> tidak ada slot terbuang.
        self.assertEqual(len(slugs), 6)

    def test_semua_gagal_502(self):
        res = self._get(
            at=_T0,
            komiku=RuntimeError('x'),
            kiryuu=RuntimeError('x'),
            vora=RuntimeError('x'),
            shn=RuntimeError('x'),
        )
        self.assertEqual(res.status_code, 502)


class RotateHelperTest(unittest.TestCase):
    """Uji unit murni helper rotasi (tanpa HTTP)."""

    def test_jatah_merata_per_sumber(self):
        pools = {n: _pool(10, n) for n in app_module.REC_SOURCES}
        out = app_module._rotate_recommended(pools, 0, 20)
        counts = {}
        for c in out:
            counts[c['source']] = counts.get(c['source'], 0) + 1
        self.assertEqual(counts, {n: 5 for n in app_module.REC_SOURCES})

    def test_order_sumber_berotasi(self):
        pools = {n: _pool(10, n) for n in app_module.REC_SOURCES}
        firsts = [app_module._rotate_recommended(pools, s, 20)[0]['source']
                  for s in range(4)]
        self.assertEqual(sorted(set(firsts)), sorted(app_module.REC_SOURCES))

    def test_isi_slot_dari_sumber_tersisa(self):
        pools = {'komiku': _pool(10, 'komiku'), 'kiryuu': [], 'voratoon': [], 'shinigami': []}
        out = app_module._rotate_recommended(pools, 0, 12)
        self.assertEqual(len(out), 10)
        self.assertTrue(all(c['source'] == 'komiku' for c in out))

    def test_pool_kosong_semua(self):
        self.assertEqual(app_module._rotate_recommended({}, 0, 20), [])


if __name__ == '__main__':
    unittest.main()
