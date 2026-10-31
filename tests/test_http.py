"""HTTP/authentication smoke checks with temporary credentials; no Headscale calls."""
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        auth = Path(cls.temp.name) / 'auth.json'
        cls.password = 'only-a-test-password'
        salt = 'ab' * 24
        auth.write_text(json.dumps({'username': 'tester', 'salt': salt,
            'hash': hashlib.pbkdf2_hmac('sha256', cls.password.encode(), bytes.fromhex(salt), 310000).hex()}))
        spec = importlib.util.spec_from_file_location('admin_test', Path(__file__).resolve().parents[1] / 'src/server.py')
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {'AUROSA_ADMIN_AUTH': str(auth), 'AUROSA_ADMIN_ORIGIN': 'https://admin.example.com'}):
            spec.loader.exec_module(cls.module)
        cls.server = cls.module.Server(('127.0.0.1', 0), cls.module.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=5)
        c.request(method, path, json.dumps(data) if data is not None else None, headers or {})
        response = c.getresponse(); result = (response.status, dict(response.getheaders()), response.read())
        c.close(); return result

    def test_public_asset_and_protected_state(self):
        self.assertEqual(self.request('GET', '/app.js?v=test')[0], 200)
        self.assertEqual(self.request('GET', '/api/state')[0], 401)

    def test_origin_and_csrf(self):
        self.assertEqual(self.request('POST', '/api/login', {'username': 'tester', 'password': self.password})[0], 403)
        headers = {'Origin': 'https://admin.example.com', 'Content-Type': 'application/json'}
        status, response, body = self.request('POST', '/api/login', {'username': 'tester', 'password': self.password}, headers)
        self.assertEqual(status, 200)
        self.assertIn('Secure', response['Set-Cookie']); self.assertIn('HttpOnly', response['Set-Cookie'])
        headers['Cookie'] = response['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('POST', '/api/logout', {}, headers)[0], 403)
        headers['X-CSRF-Token'] = json.loads(body)['csrf']
        self.assertEqual(self.request('POST', '/api/logout', {}, headers)[0], 200)

    def test_long_term_mode_off_does_not_invoke_cli(self):
        with patch.dict(os.environ, {'HEADSCALE_ALLOW_DB_KEYS': '0'}), patch.object(self.module, 'hs') as cli:
            with self.assertRaises(ValueError):
                self.module.create_access_key({'user': 1, 'expiration': 'never'})
            cli.assert_not_called()


if __name__ == '__main__':
    unittest.main()
