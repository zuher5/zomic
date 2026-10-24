import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module


ROOT = Path(__file__).resolve().parents[1]


class AccountConfigTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app)

    def test_account_config_disabled_without_settings(self):
        with patch.object(app_module, 'SUPABASE_URL', ''), \
             patch.object(app_module, 'SUPABASE_ANON_KEY', ''):
            response = self.client.get('/api/account/config')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'enabled': False, 'url': '', 'anon_key': ''})
        self.assertEqual(response.headers.get('cache-control'), 'no-store')

    def test_account_config_exposes_only_public_client_values(self):
        with patch.object(app_module, 'SUPABASE_URL', 'https://demo.supabase.co/'), \
             patch.object(app_module, 'SUPABASE_ANON_KEY', 'public-anon-key'):
            response = self.client.get('/api/account/config')
        self.assertEqual(response.json(), {
            'enabled': True,
            'url': 'https://demo.supabase.co',
            'anon_key': 'public-anon-key',
        })
        self.assertNotIn('service_role', response.text)

    def test_service_role_key_is_never_exposed(self):
        # Legacy JWT service_role key must fail closed just like sb_secret_*.
        import base64
        payload = base64.urlsafe_b64encode(b'{"role":"service_role"}').decode().rstrip('=')
        secret = 'eyJhbGciOiJub25lIn0.' + payload + '.signature'
        with patch.object(app_module, 'SUPABASE_URL', 'https://demo.supabase.co'), \
             patch.object(app_module, 'SUPABASE_ANON_KEY', secret):
            response = self.client.get('/api/account/config')
        self.assertFalse(response.json()['enabled'])
        self.assertEqual(response.json()['anon_key'], '')

    def test_secret_prefix_key_is_never_exposed(self):
        with patch.object(app_module, 'SUPABASE_URL', 'https://demo.supabase.co'), \
             patch.object(app_module, 'SUPABASE_ANON_KEY', 'sb_secret_never-send'):
            response = self.client.get('/api/account/config')
        self.assertFalse(response.json()['enabled'])
        self.assertNotIn('sb_secret', response.text)

    def test_insecure_remote_http_url_disables_account_sync(self):
        with patch.object(app_module, 'SUPABASE_URL', 'http://demo.supabase.co'), \
             patch.object(app_module, 'SUPABASE_ANON_KEY', 'public-anon-key'):
            response = self.client.get('/api/account/config')
        self.assertFalse(response.json()['enabled'])
        self.assertEqual(response.json()['url'], '')

    def test_localhost_http_allowed_for_local_supabase(self):
        with patch.object(app_module, 'SUPABASE_URL', 'http://localhost:54321'), \
             patch.object(app_module, 'SUPABASE_ANON_KEY', 'public-anon-key'):
            response = self.client.get('/api/account/config')
        self.assertTrue(response.json()['enabled'])

    def test_supabase_url_rejects_path_credentials_and_bad_host(self):
        for url in ('https://demo.supabase.co/path', 'https://user@demo.supabase.co',
                    'https://demo.supabase.co;evil.example', 'https://demo..supabase.co'):
            with self.subTest(url=url), \
                 patch.object(app_module, 'SUPABASE_URL', url), \
                 patch.object(app_module, 'SUPABASE_ANON_KEY', 'public-anon-key'):
                self.assertFalse(self.client.get('/api/account/config').json()['enabled'])

    def test_csp_is_same_origin_when_no_supabase_configured(self):
        response = self.client.get('/api/account/config')
        csp = response.headers['content-security-policy']
        self.assertIn("connect-src 'self'", csp)
        self.assertIn('frame-ancestors \'none\'', csp)
        self.assertNotIn('https://*.supabase.co', csp)

    def test_supabase_csp_origin_is_sanitized(self):
        self.assertEqual(app_module._supabase_origin('https://demo.supabase.co'), 'https://demo.supabase.co')
        self.assertEqual(app_module._supabase_origin('https://demo.supabase.co;evil'), '')


class AccountSyncFrontendTest(unittest.TestCase):
    def test_account_sync_is_optional_and_local_first(self):
        html = (ROOT / 'web' / 'index.html').read_text()
        self.assertIn("const favs = () => store.get('zomic:favs', {});", html)
        self.assertIn("fetch('/api/account/config')", html)
        self.assertIn('Sync failed — local favorites are safe.', html)
        self.assertIn('accountRowsLocal()', html)
        self.assertIn("/rest/v1/bookmarks?on_conflict=user_id,comic_slug", html)
        self.assertIn("accountAuthRequest('otp?redirect_to='", html)
        self.assertIn('accountScheduleSync();', html)
        self.assertIn("const DEVICE_FAVS_KEY = 'zomic:device-favs';", html)
        self.assertIn("const accountFavsKey = userId => 'zomic:account-favs:' + userId;", html)
        self.assertIn("accountShowDeviceFavorites();", html)

    def test_sql_enables_rls_and_scopes_every_policy_to_auth_uid(self):
        sql = (ROOT / 'supabase' / 'bookmarks.sql').read_text().lower()
        self.assertIn('alter table public.bookmarks enable row level security', sql)
        self.assertEqual(sql.count('auth.uid()'), 4)
        self.assertIn('on delete cascade', sql)
        self.assertIn('revoke all on table public.bookmarks from anon', sql)
        self.assertIn('grant select, insert, update on table public.bookmarks to authenticated', sql)
        self.assertIn('primary key (user_id, comic_slug)', sql)


if __name__ == '__main__':
    unittest.main()
