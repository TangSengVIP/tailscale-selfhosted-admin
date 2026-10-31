"""Create an admin password hash interactively; no plaintext credentials on disk."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', default='/etc/headscale-admin/auth.json')
parser.add_argument('--username', required=True)
args = parser.parse_args()
target = Path(args.output)
if target.exists():
    parser.error('Credential file already exists; use the web UI to change the password.')
if not args.username.strip():
    parser.error('Username cannot be empty.')
password = getpass.getpass('Administrator password (12-128 characters): ')
if not 12 <= len(password) <= 128:
    parser.error('Password must be 12-128 characters.')
if password != getpass.getpass('Repeat password: '):
    parser.error('Passwords do not match.')
salt = secrets.token_hex(24)
auth = {'username': args.username.strip(), 'salt': salt,
        'hash': hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()}
target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='utf-8') as stream:
    json.dump(auth, stream)
print('Password hash created:', target)
