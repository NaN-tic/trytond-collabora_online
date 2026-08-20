from trytond.model import fields
from trytond.pool import PoolMeta
from trytond.pyson import Bool, Eval

from .editor import get_editor_url, is_editable_filename


class Attachment(metaclass=PoolMeta):
    __name__ = 'ir.attachment'

    edit_url = fields.Function(
        fields.Char('Edit URL', states={
                'invisible': ~Bool(Eval('edit_url')),
                }),
        'get_edit_url')

    @classmethod
    def get_edit_url(cls, attachments, name):
        return {
            attachment.id: (
                get_editor_url(cls.__name__, attachment.id, 'data',
                    attachment.name)
                if attachment.type == 'data'
                and is_editable_filename(attachment.name) else None)
            for attachment in attachments}
