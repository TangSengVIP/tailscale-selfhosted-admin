"""Recoverable key display must be group-scoped and respect revocation."""
import ast
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

source = Path(__file__).resolve().parents[1] / 'src/server.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
names = {'positive_id', 'timestamp', 'key_prefix', 'access_key_vault', 'remember_access_key', 'group_access_keys'}
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]


class KeyVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'access-keys.json'
        self.prefix = 'hskey-auth-' + 'a'*12
        self.secret = self.prefix + 'b'*40
        self.keys = [{'id': 1, 'key': self.prefix + '***', 'user': {'id': 6}, 'reusable': True}]
        def hs(*args):
            return [{'id': 6}, {'id': 7}] if args == ('users', 'list') else self.keys
        self.ns = {'os': os, 'json': json, 'LOCK': threading.RLock(), 'time': time,
                   'ACCESS_KEYS_PATH': self.path, 'hs': hs}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), self.ns)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, user=6):
        self.ns['remember_access_key']({'id': 1, 'key': self.secret}, user)

    def test_saved_key_roundtrip_and_file_permissions(self):
        self.save()
        self.assertEqual(self.ns['group_access_keys'](6)[0]['key'], self.secret)
        self.assertFalse(self.path.with_suffix('.new').exists())
        if os.name != 'nt':self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_historical_key_unrecoverable(self):
        self.assertIsNone(self.ns['group_access_keys'](6)[0]['key'])

    def test_group_boundary(self):
        self.save()
        self.assertEqual(self.ns['group_access_keys'](7), [])
        self.save(user=7)
        self.assertIsNone(self.ns['group_access_keys'](6)[0]['key'])

    def test_expired_and_used_do_not_reveal_secret(self):
        self.save()
        self.keys[0]['expiration'] = {'seconds': 1}
        self.assertIsNone(self.ns['group_access_keys'](6)[0]['key'])
        self.keys[0].pop('expiration');self.keys[0].update(used=True,reusable=False)
        self.assertIsNone(self.ns['group_access_keys'](6)[0]['key'])

    def test_reused_identifier_or_wrong_prefix(self):
        self.save();self.keys[0]['key'] = 'hskey-auth-' + 'c'*12 + '***'
        self.assertIsNone(self.ns['group_access_keys'](6)[0]['key'])

    def test_nonexistent_group(self):
        with self.assertRaises(ValueError):self.ns['group_access_keys'](99)


if __name__ == '__main__':unittest.main()
