import datetime as dt
import json
import mimetypes
import os
from urllib.parse import quote, urlencode

from werkzeug.exceptions import abort
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

from trytond.config import config
from trytond.model import fields
from trytond.model.exceptions import AccessError
from trytond.pyson import PYSONDecoder, PYSONEncoder
from trytond.protocols.wrappers import (
    HTTPStatus, with_pool, with_transaction)
from trytond.transaction import Transaction, check_access
from trytond.wsgi import app

from . import wopi_token

LOCK_SECONDS = 30 * 60


def _binary_field(pool, model_name, field_name):
    try:
        Model = pool.get(model_name)
        field = Model._fields[field_name]
    except (KeyError, AttributeError):
        abort(404)
    if not isinstance(field, fields.Binary):
        abort(404)
    return Model, field


def _safe_name(name, field):
    name = (name or field).replace('/', '_').replace('\\', '_').strip()
    return name[:255] or field


def _rename_field(Model, binary):
    name = binary.filename
    if not name or name not in Model._fields:
        return None
    return name


def _requested_name(request, current_name):
    name = request.headers.get('X-WOPI-RequestedName', '').strip()
    if (not name or len(name) > 255 or '/' in name or '\\' in name
            or any(ord(char) < 32 for char in name)):
        return None
    # WOPI specifies a name without an extension.  Retain the extension stored
    # by Tryton; accepting one from a client would silently change file type.
    stem = os.path.splitext(name)[0]
    if not stem:
        return None
    return stem + os.path.splitext(current_name or '')[1], stem


def _writable(pool, model_name, field_name, record, field):
    """Test the same model, field and record rules as a normal write."""
    if field.readonly:
        return False
    readonly = field.states.get('readonly')
    if readonly:
        values = record.__class__.read(
            [record.id], list(field.depends | {'id'}))[0]
        values['context'] = Transaction().context
        if PYSONDecoder(values).decode(PYSONEncoder().encode(readonly)):
            return False
    ModelAccess = pool.get('ir.model.access')
    FieldAccess = pool.get('ir.model.field.access')
    if not ModelAccess.check(model_name, 'write', raise_exception=False):
        return False
    if not FieldAccess.check(
            model_name, [field_name], 'write', raise_exception=False):
        return False
    try:
        # read with the current user makes record rules explicit before a
        # capability is minted.  Writes are checked again on every callback.
        record.__class__.read([record.id], [field_name])
    except AccessError:
        return False
    return True


def _claim_record(pool, claim, write=False):
    Model, field = _binary_field(pool, claim['model'], claim['field'])
    if write and (not claim['writable'] or field.readonly):
        abort(403)
    try:
        with Transaction().set_user(claim['user']), check_access():
            record = Model(claim['record'])
            Model.read([record.id], [claim['field']])
            if write and not _writable(
                    pool, claim['model'], claim['field'], record, field):
                abort(403)
    except AccessError:
        # Do not disclose the existence of a record the user can no longer see.
        abort(404)
    return Model, field, record


def _version(record):
    value = getattr(record, 'write_date', None) or getattr(
        record, 'create_date', None)
    return str(value.isoformat() if value else record.id)


def _response(data=b'', status=200, **headers):
    response = Response(data, status=status)
    for name, value in headers.items():
        response.headers[name.replace('_', '-')] = str(value)
    return response


def _json_response(data, status=200, **headers):
    response = _response(
        json.dumps(data, separators=(',', ':')), status, **headers)
    response.content_type = 'application/json'
    return response


def _current_lock(Lock, file_id):
    locks = Lock.search([('file_id', '=', file_id)], limit=1)
    if not locks:
        return None
    lock, = locks
    if lock.expires_at <= dt.datetime.utcnow():
        Lock.delete([lock])
        return None
    return lock


def _lock_conflict(lock):
    return _response(status=409, X_WOPI_Lock=lock.value if lock else '',
        X_WOPI_LockFailureReason='Lock mismatch')


def _lock_value(request):
    value = request.headers.get('X-WOPI-Lock')
    if not value or len(value) > 1024 or not value.isascii():
        abort(400)
    return value


@app.route('/<database_name>/collabora/open/<string:model>/<int:record>/<field>',
    methods={'GET'})
@app.auth_required
@with_pool
@with_transaction(user='request', context={'_check_access': True})
def open_editor(request, pool, model, record, field):
    Model, binary = _binary_field(pool, model, field)
    try:
        current = Model(record)
        Model.read([record], [field])
    except AccessError:
        abort(404)
    writable = _writable(pool, model, field, current, binary)
    name = _safe_name(request.args.get('name'), field)
    file_id, access_token = wopi_token.make(
        Transaction().database.name, Transaction().user, model, record, field,
        writable, name)
    host_url = config.get('collabora', 'wopi_url')
    collabora_url = config.get('collabora', 'url')
    if not host_url or not collabora_url:
        abort(HTTPStatus.SERVICE_UNAVAILABLE)
    wopi_src = '%s/%s/wopi/files/%s' % (
        host_url.rstrip('/'), quote(Transaction().database.name, safe=''), file_id)
    # Collabora's browser route accepts the standard WOPISrc and access_token
    # parameters.  This response is suitable for an ir.action.url with target
    # "new", so no Sao integration or second login is involved.
    url = '%s/browser/dist/cool.html?%s' % (
        collabora_url.rstrip('/'), urlencode({
            'WOPISrc': wopi_src, 'access_token': access_token,
            'permission': 'edit' if writable else 'view'}))
    return redirect(url)


@app.route('/<database_name>/wopi/files/<file_id>', methods={'GET', 'POST'})
@with_pool
@with_transaction(readonly=False)
def file(request, pool, file_id):
    claim = wopi_token.check(request.view_args['database_name'], file_id,
        request.args.get('access_token', ''))
    Model, binary, record = _claim_record(pool, claim)
    if request.method == 'GET':
        extension = mimetypes.guess_extension(
            mimetypes.guess_type(claim['name'])[0] or '') or ''
        name = claim['name']
        if extension and not name.lower().endswith(extension):
            name += extension
        return _json_response({
            'BaseFileName': name,
            'OwnerId': str(claim['user']),
            'Size': len(getattr(record, claim['field']) or b''),
            'UserId': str(claim['user']),
            'UserCanNotWriteRelative': True,
            'UserCanRename': bool(
                claim['writable'] and _rename_field(Model, binary)
                and _writable(pool, claim['model'], binary.filename,
                    record, Model._fields[binary.filename])),
            'UserCanWrite': bool(claim['writable']),
            'UserFriendlyName': str(claim['user']),
            'Version': _version(record),
            'ReadOnly': not claim['writable'],
            'SupportsExtendedLockLength': True,
            'SupportsGetLock': True,
            'SupportsLocks': True,
            'SupportsRename': bool(_rename_field(Model, binary)),
            'SupportsUpdate': bool(claim['writable']),
            })
    override = request.headers.get('X-WOPI-Override', '').upper()
    if override != 'GET_LOCK' and not claim['writable']:
        abort(403)
    Lock = pool.get('collabora.online.lock')
    lock = _current_lock(Lock, file_id)
    if override == 'GET_LOCK':
        return _response(X_WOPI_Lock=lock.value if lock else '')
    if override == 'LOCK':
        value = _lock_value(request)
        if lock and lock.value != value:
            return _lock_conflict(lock)
        expires = dt.datetime.utcnow() + dt.timedelta(seconds=LOCK_SECONDS)
        if lock:
            Lock.write([lock], {'expires_at': expires})
        else:
            Lock.create([{'file_id': file_id, 'value': value, 'expires_at': expires}])
        return _response()
    if override == 'REFRESH_LOCK':
        value = _lock_value(request)
        if not lock or lock.value != value:
            return _lock_conflict(lock)
        Lock.write([lock], {'expires_at': dt.datetime.utcnow()
            + dt.timedelta(seconds=LOCK_SECONDS)})
        return _response()
    if override == 'UNLOCK':
        value = _lock_value(request)
        if not lock or lock.value != value:
            return _lock_conflict(lock)
        Lock.delete([lock])
        return _response()
    if override == 'UNLOCK_AND_RELOCK':
        value = _lock_value(request)
        new_value = request.headers.get('X-WOPI-OldLock')
        if not lock or lock.value != new_value:
            return _lock_conflict(lock)
        Lock.write([lock], {'value': value, 'expires_at': dt.datetime.utcnow()
            + dt.timedelta(seconds=LOCK_SECONDS)})
        return _response()
    if override == 'DELETE':
        Model, _binary, record = _claim_record(pool, claim, write=True)
        requested = request.headers.get('X-WOPI-Lock', '')
        if lock and lock.value != requested:
            return _lock_conflict(lock)
        try:
            with Transaction().set_user(claim['user']), check_access():
                Model.write([record], {claim['field']: None})
        except AccessError:
            abort(403)
        if lock:
            Lock.delete([lock])
        return _response()
    if override == 'RENAME_FILE':
        Model, binary, record = _claim_record(pool, claim, write=True)
        filename = _rename_field(Model, binary)
        if not filename or not _writable(
                pool, claim['model'], filename, record,
                Model._fields[filename]):
            abort(501)
        requested = request.headers.get('X-WOPI-Lock', '')
        if lock and lock.value != requested:
            return _lock_conflict(lock)
        current_name = getattr(record, filename) or claim['name']
        result = _requested_name(request, current_name)
        if not result:
            return _response(status=400,
                X_WOPI_InvalidFileNameError='Invalid file name')
        new_name, stem = result
        try:
            with Transaction().set_user(claim['user']), check_access():
                Model.write([record], {filename: new_name})
        except AccessError:
            abort(403)
        return {'Name': stem}
    abort(501)


@app.route('/<database_name>/wopi/files/<file_id>/contents',
    methods={'GET', 'POST'})
@with_pool
@with_transaction(readonly=False)
def contents(request, pool, file_id):
    claim = wopi_token.check(request.view_args['database_name'], file_id,
        request.args.get('access_token', ''))
    if request.method == 'GET':
        _Model, _binary, record = _claim_record(pool, claim)
        data = getattr(record, claim['field']) or b''
        content_type = (
            mimetypes.guess_type(claim['name'])[0]
            or 'application/octet-stream')
        return _response(data, Content_Type=content_type)
    if request.headers.get('X-WOPI-Override', '').upper() != 'PUT':
        abort(501)
    Model, _binary, record = _claim_record(pool, claim, write=True)
    Lock = pool.get('collabora.online.lock')
    lock = _current_lock(Lock, file_id)
    requested = request.headers.get('X-WOPI-Lock', '')
    old_data = getattr(record, claim['field']) or b''
    if (lock and lock.value != requested) or (not lock and old_data):
        return _lock_conflict(lock)
    try:
        with Transaction().set_user(claim['user']), check_access():
            Model.write([record], {claim['field']: request.get_data()})
    except AccessError:
        abort(403)
    return _response(X_WOPI_ItemVersion=_version(record))
