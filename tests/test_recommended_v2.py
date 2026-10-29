import unittest
from unittest.mock import patch

import app as app_module
from app import KomikuAPI, _build_recommended_v2, _primary_genre


def card(slug, title, genre='Drama', source='komiku'):
    return {'slug': slug, 'title': title, 'genre': genre, 'cover': '', 'type': 'Manga',
            'source': source}


class PrimaryGenreTest(unittest.TestCase):
    def test_string_and_list(self):
        self.assertEqual(_primary_genre({'genre': 'Action Drama'}), 'action')
        self.assertEqual(_primary_genre({'genre': ['Romance', 'Drama']}), 'romance')
        self.assertEqual(_primary_genre({'genre': ''}), '')


class BuildV2Test(unittest.TestCase):
    def test_mixes_wide_and_similar_within_limit(self):
        wide = [card(f'w{i}', f'Wide {i}', genre=f'g{i}') for i in range(10)]
        sim = [[card(f's{i}', f'Sim {i}', genre=f'h{i}') for i in range(5)]]
        out = _build_recommended_v2(wide, sim, step=0, limit=10)
        self.assertEqual(len(out), 10)
        slugs = [c['slug'] for c in out]
        self.assertTrue(any(s.startswith('w') for s in slugs))
        self.assertTrue(any(s.startswith('s') for s in slugs))

    def test_genre_cap_limits_single_genre(self):
        wide = [card(f'a{i}', f'Action {i}', genre='Action') for i in range(20)]
        out = _build_recommended_v2(wide, [], step=0, limit=20)
        self.assertLessEqual(len(out), app_module.REC_GENRE_CAP)

    def test_dedup_by_slug_and_title(self):
        wide = [card('x', 'Same Title'), card('y', 'same  title!'), card('z', 'Other')]
        out = _build_recommended_v2(wide, [], step=0, limit=10)
        self.assertEqual([c['slug'] for c in out], ['x', 'z'])

    def test_rotation_changes_set_between_windows(self):
        wide = [card(f'w{i}', f'Wide {i}', genre=f'g{i}') for i in range(12)]
        a = {c['slug'] for c in _build_recommended_v2(wide, [], step=0, limit=6)}
        b = {c['slug'] for c in _build_recommended_v2(wide, [], step=3, limit=6)}
        self.assertNotEqual(a, b)

    def test_consecutive_windows_change_most_items(self):
        wide = [card(f'w{i}', f'Wide {i}', genre=f'g{i}') for i in range(60)]
        prev = {c['slug'] for c in _build_recommended_v2(wide, [], step=0, limit=20)}
        for step in range(1, 4):
            cur = {c['slug'] for c in _build_recommended_v2(wide, [], step=step, limit=20)}
            overlap = len(cur & prev) / len(cur)
            self.assertLessEqual(overlap, 0.5, f'step {step} overlap {overlap}')
            prev = cur

    def test_all_sources_represented_each_window(self):
        def c(slug, src, genre):
            return {'slug': slug, 'title': slug, 'source': src, 'genre': genre,
                    'cover': '', 'type': 'Manga'}
        wide = ([c(f'k{i}', 'komiku', f'g{i}') for i in range(40)]
                + [c(f'r{i}', 'kiryuu', f'h{i}') for i in range(10)]
                + [c(f'v{i}', 'voratoon', f'j{i}') for i in range(10)]
                + [c(f's{i}', 'shinigami', f'q{i}') for i in range(10)])
        for step in range(4):
            out = _build_recommended_v2(wide, [], step, 20)
            srcs = {x['source'] for x in out}
            self.assertEqual(srcs, {'komiku', 'kiryuu', 'voratoon', 'shinigami'},
                             f'step {step}')

    def test_empty_inputs_return_empty(self):
        self.assertEqual(_build_recommended_v2([], [], step=0, limit=5), [])


class SimilarParserTest(unittest.TestCase):
    def test_filters_testing_entries_and_normalizes(self):
        detail = {'similarKomik': [
            {'title': '[testing ikiru] Bad', 'slug': 'bad', 'thumbnail': 'https://x/a.jpg',
             'genres': ['Drama'], 'apiLink': '/detail-komik/bad'},
            {'title': 'Good One', 'slug': 'good-one', 'thumbnail': 'https://x/b.jpg',
             'genres': ['Action'], 'apiLink': '/detail-komik/good-one'},
        ]}
        api = KomikuAPI()
        with patch.object(api, '_get', return_value=detail):
            out = api.similar('ao-ashi')
        self.assertEqual([c['slug'] for c in out], ['good-one'])
        self.assertEqual(out[0]['source'], 'komiku')

    def test_non_dict_response_is_empty(self):
        api = KomikuAPI()
        with patch.object(api, '_get', return_value=[]):
            self.assertEqual(api.similar('x'), [])


if __name__ == '__main__':
    unittest.main()
