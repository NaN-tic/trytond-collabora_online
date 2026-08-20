"""Stateless, short-lived WOPI capabilities.

The file identifier is an encoded claim and the access token is its HMAC.  It
is intentionally not a Tryton session token: Collabora only receives the
minimum capability needed to operate on one binary field.
"""
import base64
import binascii
import hashlib
import hmac
import json
import time

from trytond.config import config
from werkzeug.exceptions import abort


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _decode(value):
    padding = '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode('ascii'))


def _secret():
    secret = config.get('collabora', 'wopi_secret', default='')
    if len(secret.encode('utf-8')) < 32:
        raise RuntimeError(
            'collabora.wopi_secret must contain at least 32 bytes')
    return secret.encode('utf-8')


def make(database, user, model, record, field, writable, name):
    lifetime = config.getint('collabora', 'token_lifetime', default=1800)
    now = int(time.time())
    claim = {
        'database': database,
        'expires': now + lifetime,
        'field': field,
        'model': model,
        'name': name,
        'record': record,
        'user': user,
        'writable': bool(writable),
        }
    file_id = _encode(json.dumps(
            claim, sort_keys=True, separators=(',', ':')).encode('utf-8'))
    signature = hmac.new(
        _secret(), ('%s:%s' % (database, file_id)).encode('ascii'),
        hashlib.sha256).digest()
    return file_id, _encode(signature)


def check(database, file_id, access_token):
    try:
        expected = _encode(hmac.new(
                _secret(), ('%s:%s' % (database, file_id)).encode('ascii'),
                hashlib.sha256).digest())
        if not hmac.compare_digest(expected, access_token):
            raise ValueError
        claim = json.loads(_decode(file_id))
        required = {'database', 'expires', 'field', 'model', 'name', 'record',
            'user', 'writable'}
        if (set(claim) != required or claim['database'] != database
                or not isinstance(claim['expires'], int)
                or claim['expires'] < int(time.time())):
            raise ValueError
    except (TypeError, ValueError, UnicodeError, binascii.Error,
            json.JSONDecodeError):
        abort(401)
    return claim
