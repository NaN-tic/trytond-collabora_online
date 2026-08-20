from pathlib import PurePath
from urllib.parse import quote, urlencode

from trytond.config import config
from trytond.transaction import Transaction


# Formats that Collabora Online can edit, rather than merely preview.  This is
# deliberately conservative: offering an editor for a viewer-only format is a
# misleading user experience.
EDITABLE_EXTENSIONS = frozenset({
    '.csv', '.doc', '.docm', '.docx', '.fodg', '.fodp', '.fods', '.fodt',
    '.htm', '.html', '.odp', '.ods', '.odt', '.otp', '.ots', '.ott', '.ppt',
    '.pptm', '.pptx', '.rtf', '.txt', '.xls', '.xlsm', '.xlsx',
    })


def is_editable_filename(name):
    return PurePath(name or '').suffix.lower() in EDITABLE_EXTENSIONS


def get_editor_url(model, record, field, name=None):
    """Return the authenticated launch URL for a Tryton binary field.

    This is intentionally the URL of Tryton's launch endpoint, not the
    Collabora URL and not a WOPI token.  It is therefore safe to expose on a
    record and can only be used by a browser with a valid Tryton session.
    """
    url_root = config.get('collabora', 'wopi_url')
    if not url_root or not record:
        return None
    database = Transaction().database.name
    path = '/%s/collabora/open/%s/%s/%s' % (
        quote(database, safe=''), quote(model, safe=''), record,
        quote(field, safe=''))
    query = urlencode({'name': name}) if name else ''
    return '%s%s%s' % (url_root.rstrip('/'), path,
        ('?' + query) if query else '')
