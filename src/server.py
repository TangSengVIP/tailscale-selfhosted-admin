"""Aurosa Chinese administration for Headscale 0.29; standard library only."""
import base64
import collections
import hashlib
import hmac
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import sqlite3
import subprocess
import threading
import time
import unicodedata

ROOT = Path(__file__).resolve().parent
AUTH_PATH = Path(os.environ.get('AUROSA_ADMIN_AUTH', '/etc/headscale-admin/auth.json'))
AUTH = json.loads(AUTH_PATH.read_text())
ORIGIN = os.environ.get('AUROSA_ADMIN_ORIGIN', 'https://headscale.example.com')
COOKIE_PATH = os.environ.get('AUROSA_ADMIN_COOKIE_PATH', '/')
HEADSCALE_URL = os.environ.get('HEADSCALE_URL', ORIGIN).rstrip('/')
HEADSCALE_BIN = os.environ.get('HEADSCALE_BIN', '/usr/local/bin/headscale')
HEADSCALE_CONFIG = os.environ.get('HEADSCALE_CONFIG', '/etc/headscale/config.yaml')
HEADSCALE_DB = os.environ.get('HEADSCALE_DB', '/var/lib/headscale/db.sqlite')
ADMIN_GROUP = os.environ.get('AUROSA_ADMIN_GROUP', 'admin')
SESSIONS = {}
FAILURES = collections.OrderedDict()
LOCK = threading.RLock()
CLI_LOCK = threading.Lock()
POLICY_LOCK = threading.RLock()
DEVICE_NAMES_PATH = AUTH_PATH.parent / 'device-names.json'


def device_names():
    if not DEVICE_NAMES_PATH.exists():
        return {}
    return json.loads(DEVICE_NAMES_PATH.read_text(encoding='utf-8'))


def rename_device(identifier, value, client_name=None):
    identifier = positive_id(identifier)
    if not isinstance(value, str):
        raise ValueError('请输入设备名称')
    value = unicodedata.normalize('NFC', value.strip())
    if not 1 <= len(value) <= 63 or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('设备名称需为 1–63 个字符，不能包含控制字符')
    if client_name is not None:
        if not isinstance(client_name, str):
            raise ValueError('客户端名称无效')
        client_name = client_name.strip().lower()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', client_name):
            raise ValueError('客户端名称需为 1–63 位英文、数字或短横线，首尾须为英文或数字')
    with LOCK:
        nodes = hs('nodes', 'list') or []
        node = next((n for n in nodes if str(n['id']) == identifier), None)
        if not node:
            raise ValueError('设备不存在')
        if client_name is not None:
            if any(str(n['id']) != identifier and n.get('given_name') == client_name for n in nodes):
                raise ValueError('客户端名称已被其他设备使用')
            if client_name != node.get('given_name'):
                hs('nodes', 'rename', client_name, '--identifier='+identifier)
        names = device_names()
        names[identifier] = value
        temporary = DEVICE_NAMES_PATH.with_suffix('.new')
        temporary.write_text(json.dumps(names, ensure_ascii=False), encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(DEVICE_NAMES_PATH)


def mutual_rule(name):
    selector = name + '@'
    return {'action': 'accept', 'src': [selector], 'dst': [selector + ':*']}


def user_mutual_access(user_id, enabled):
    if not isinstance(enabled, bool):
        raise ValueError('开关状态无效')
    identifier = positive_id(user_id)
    with POLICY_LOCK:
        users = hs('users', 'list') or []
        user = next((u for u in users if str(u['id']) == identifier), None)
        if not user:
            raise ValueError('用户不存在')
        policy = hs('policy', 'get')
        rule = mutual_rule(user['name'])
        rules = [r for r in policy.get('acls', []) if r != rule]
        if enabled:
            rules.append(rule)
        policy['acls'] = rules
        path = AUTH_PATH.parent / 'policy-update.json'
        try:
            path.write_text(json.dumps(policy))
            path.chmod(0o600)
            hs('policy', 'set', '--file='+str(path))
        finally:
            path.unlink(missing_ok=True)


def password_ok(password, auth=None):
    auth = auth or AUTH
    if not isinstance(password, str) or len(password) > 512:
        return False
    value = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(auth['salt']), 310000)
    return hmac.compare_digest(value.hex(), auth['hash'])


def hs(*args):
    with CLI_LOCK:
        result = subprocess.run([HEADSCALE_BIN, '-c', HEADSCALE_CONFIG,
                                 *args, '-o', 'json'], capture_output=True, text=True, timeout=20)
    if result.returncode:
        # Do not pass CLI output (which may contain keys) back to the browser.
        raise ValueError('操作未完成，请检查对象是否存在、名称是否重复，或稍后重试。')
    if args[:2] == ('policy', 'set'):
        return None  # This CLI emits plain text even with -o json.
    return json.loads(result.stdout) if result.stdout.strip() else None


def positive_id(value):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError('无效的编号')
    return str(int(value))


def create_access_key(data):
    expiration = data.get('expiration')
    if expiration not in ('10m', '1h', '24h', '168h', 'never'):
        raise ValueError('请选择有效的密钥期限')
    if expiration == 'never' and os.environ.get('HEADSCALE_ALLOW_DB_KEYS') != '1':
        raise ValueError('长期密钥需要管理员按部署说明显式启用数据库兼容模式。')
    user = positive_id(data.get('user'))
    args = ['preauthkeys', 'create', '--user='+user,
            '--expiration='+('24h' if expiration == 'never' else expiration)]
    if data.get('reusable') is True:
        args.append('--reusable')
    if data.get('ephemeral') is True:
        args.append('--ephemeral')
    key = hs(*args)
    if expiration == 'never':
        try:
            # Headscale 0.29.6's model supports NULL expiry, but its CLI/API
            # always provides a timestamp. Registration reads this row afresh.
            with sqlite3.connect(HEADSCALE_DB, timeout=10) as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT user_id,prefix,tags,used FROM pre_auth_keys WHERE id=?',
                                 (key['id'],)).fetchone()
                if (not row or row[0] != int(user) or row[1] != key['key'][11:23]
                        or json.loads(row[2] or '[]') or row[3]):
                    raise ValueError('新密钥状态不符合预期')
                assert db.execute('UPDATE pre_auth_keys SET expiration=NULL WHERE id=?',
                                  (key['id'],)).rowcount == 1
            key['expiration'] = None
        except Exception:
            hs('preauthkeys', 'delete', '--id='+str(key['id']), '--force')
            raise ValueError('长期密钥生成失败，请稍后重试。') from None
    return key


def safe_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}', value):
        raise ValueError('名称需为 1–63 位英文字母、数字、点、下划线或短横线。')
    return value


def timestamp(value):
    return value.get('seconds', 0) if isinstance(value, dict) else value


def coalesce_router_devices(devices):
    """Group enrollment history for display only; never use hostnames for authorization."""
    groups = {}
    for device in devices:
        hostname = device.get('hostname') or ''
        if (device.get('admin') or device.get('tags') or not device.get('user_id')
                or not re.fullmatch(r'(?:aurosa|titslee)router-[0-9a-f]{6,12}', hostname, re.I)):
            continue
        key = (str(device['user_id']), hostname.lower())
        groups.setdefault(key, []).append(device)
    hidden = set()
    replacements = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda n: (float(n.get('created') or 0), int(n['id'])), reverse=True)
        latest = ordered[0]
        # An older identity still online is not a proven superseded registration.
        if any(n.get('online') for n in ordered[1:]):
            continue
        current = dict(latest)
        if not current.get('has_note'):
            annotated = next((n for n in ordered[1:] if n.get('has_note')), None)
            if annotated:
                current['name'] = annotated['name']
                current['inherited_note'] = True
        current['registration_history'] = [dict(n) for n in ordered[1:]]
        replacements[str(latest['id'])] = current
        hidden.update(str(n['id']) for n in ordered[1:])
    return [replacements.get(str(n['id']), n) for n in devices if str(n['id']) not in hidden]


def get_state():
    nodes = hs('nodes', 'list') or []
    users = hs('users', 'list') or []
    keys = hs('preauthkeys', 'list') or []
    policy = hs('policy', 'get')
    names = device_names()
    admin_group = next((u for u in users if u['name'] == ADMIN_GROUP), None)
    def owner(node):
        if admin_group and 'tag:aurosa-admin' in (node.get('tags') or []):
            return admin_group
        return node.get('user') or {}
    result = {
        'server': HEADSCALE_URL, 'version': '0.29.6',
        'devices': [{
            'id': n['id'], 'name': names.get(str(n['id'])) or n.get('given_name') or n.get('name'),
            'has_note': bool(names.get(str(n['id']))), 'tags': n.get('tags') or [],
            'hostname': n.get('name'), 'ip': n.get('ip_addresses', []),
            'client_name': n.get('given_name') or n.get('name'),
            'user': owner(n).get('display_name') or owner(n).get('name', ''),
            'admin': 'tag:aurosa-admin' in (n.get('tags') or []),
            'user_id': owner(n).get('id'), 'online': n.get('online', False),
            'last_seen': timestamp(n.get('last_seen')), 'expiry': timestamp(n.get('expiry')),
            'created': timestamp(n.get('created_at')),
        } for n in nodes],
        'users': [{'id': u['id'], 'name': u.get('name', ''),
                   'mutual_access': mutual_rule(u['name']) in policy.get('acls', []),
                   'display_name': u.get('display_name', ''),
                   'created': timestamp(u.get('created_at'))} for u in users],
        'keys': [{'id': k['id'], 'user': k.get('user', {}).get('name', ''),
                  'used': k.get('used', False), 'reusable': k.get('reusable', False),
                  'ephemeral': k.get('ephemeral', False), 'expires': timestamp(k.get('expiration')),
                  'created': timestamp(k.get('created_at'))} for k in keys],
    }
    result['devices'] = coalesce_router_devices(result['devices'])
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = 'AurosaAdmin'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # Never log request bodies, cookies, auth keys or passwords.
        print(json.dumps({'client': self.client_address[0], 'method': self.command,
                          'path': self.path.split('?')[0], 'event': fmt % args}), flush=True)

    def respond(self, code, data, content_type='application/json; charset=utf-8', cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def session(self):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get('Cookie', ''))
            token = jar['aurosa_session'].value
        except (KeyError, cookies.CookieError):
            return None
        with LOCK:
            now = time.time()
            for old in list(SESSIONS):
                if SESSIONS[old]['expires'] <= now:
                    del SESSIONS[old]
            session = SESSIONS.get(token)
            return (token, session) if session else None

    def do_GET(self):
        self.path = self.path.split('?', 1)[0]
        if self.path in ('/', '/app.js', '/style.css'):
            name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[self.path]
            kind = {'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
            return self.respond(200, (ROOT/name).read_bytes(), kind+'; charset=utf-8')
        if self.path == '/api/session':
            session = self.session()
            return self.respond(200, {'authenticated': bool(session),
                                     'csrf': session[1]['csrf'] if session else None})
        if self.path == '/api/state':
            if not self.session():
                return self.respond(401, {'error': '请先登录'})
            try:
                return self.respond(200, get_state())
            except (ValueError, subprocess.SubprocessError, OSError):
                return self.respond(503, {'error': '暂时无法读取 Headscale 数据，请稍后刷新。'})
        self.respond(404, {'error': '页面不存在'})

    def do_POST(self):
        if self.headers.get('Origin') != ORIGIN:
            self.close_connection = True
            return self.respond(403, {'error': '请求来源校验失败'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 2 or length > 8192:
                self.close_connection = True
                return self.respond(413, {'error': '请求长度不正确'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('无效请求')
        except (ValueError, UnicodeError):
            return self.respond(400, {'error': '请求格式不正确'})
        if self.path == '/api/login':
            ip = self.client_address[0]
            with LOCK:
                now = time.time()
                history = [t for t in FAILURES.get(ip, []) if now-t < 900]
                if len(history) >= 10:
                    return self.respond(429, {'error': '尝试次数过多，请 15 分钟后再试。'})
                if data.get('username') != AUTH['username'] or not password_ok(data.get('password')):
                    FAILURES[ip] = history+[now]
                    if len(FAILURES) > 2048:
                        FAILURES.popitem(last=False)
                    return self.respond(401, {'error': '账号或密码错误'})
                FAILURES.pop(ip, None)
                token = secrets.token_urlsafe(32)
                session = {'expires': now+8*3600, 'csrf': secrets.token_urlsafe(24)}
                if len(SESSIONS) >= 128:
                    SESSIONS.pop(next(iter(SESSIONS)))
                SESSIONS[token] = session
            return self.respond(200, {'csrf': session['csrf']}, cookie=
                'aurosa_session='+token+'; HttpOnly; Secure; SameSite=Strict; Path='+COOKIE_PATH+'; Max-Age=28800')
        session = self.session()
        if not session:
            return self.respond(401, {'error': '登录已过期，请重新登录'})
        if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), session[1]['csrf']):
            return self.respond(403, {'error': '请求校验失败，请刷新页面'})
        try:
            return self.action(data, session)
        except (ValueError, subprocess.SubprocessError, OSError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else '服务操作失败，请稍后重试。'
            self.respond(400, {'error': message})

    def action(self, data, session):
        path = self.path
        if path == '/api/logout':
            with LOCK:
                SESSIONS.pop(session[0], None)
            return self.respond(200, {'ok': True}, cookie=
                'aurosa_session=; HttpOnly; Secure; SameSite=Strict; Path='+COOKIE_PATH+'; Max-Age=0')
        if path == '/api/password':
            if not password_ok(data.get('current')):
                raise ValueError('当前密码不正确')
            password = data.get('password')
            if not isinstance(password, str) or not 12 <= len(password) <= 128:
                raise ValueError('新密码长度需为 12–128 位')
            newauth = {'username': AUTH['username'], 'salt': secrets.token_hex(24)}
            newauth['hash'] = hashlib.pbkdf2_hmac('sha256', password.encode(),
                                               bytes.fromhex(newauth['salt']), 310000).hex()
            temporary = AUTH_PATH.with_suffix('.tmp')
            with LOCK:
                temporary.write_text(json.dumps(newauth))
                temporary.chmod(0o600)
                temporary.replace(AUTH_PATH)
                AUTH.clear()
                AUTH.update(newauth)
                for token in list(SESSIONS):
                    if token != session[0]:
                        del SESSIONS[token]
            return self.respond(200, {'ok': True})
        if path == '/api/users/create':
            hs('users', 'create', safe_name(data.get('name')))
        elif path == '/api/users/mutual-access':
            user_mutual_access(data.get('id'), data.get('enabled'))
        elif path == '/api/users/delete':
            identifier = positive_id(data.get('id'))
            state = get_state()
            if any(str(n.get('user', {}).get('id')) == identifier for n in (hs('nodes', 'list') or [])):
                raise ValueError('该用户仍有设备，请先处理设备再删除用户。')
            if len(state['users']) <= 1:
                raise ValueError('请至少保留一个用户。')
            user_mutual_access(identifier, False)
            hs('users', 'destroy', '--identifier='+identifier, '--force')
        elif path == '/api/devices/rename':
            rename_device(data.get('id'), data.get('name'), data.get('client_name'))
        elif path in ('/api/devices/expire', '/api/devices/delete'):
            hs('nodes', path.rsplit('/', 1)[1], '--identifier='+positive_id(data.get('id')), '--force')
        elif path == '/api/keys/create':
            key = create_access_key(data)
            return self.respond(200, {'ok': True, 'key': key['key'], 'id': key['id']})
        elif path == '/api/keys/expire':
            hs('preauthkeys', 'expire', '--id='+positive_id(data.get('id')))
        else:
            return self.respond(404, {'error': '操作不存在'})
        self.respond(200, {'ok': True})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def get_request(self):
        conn, address = super().get_request()
        conn.settimeout(20)
        return conn, address


if __name__ == '__main__':
    server = Server(('127.0.0.1', int(os.environ.get('AUROSA_ADMIN_PORT', '18444'))), Handler)
    server.serve_forever()
