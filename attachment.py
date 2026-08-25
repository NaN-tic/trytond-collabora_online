from trytond.model import fields, ModelView
from trytond.pool import PoolMeta
from trytond.pyson import Bool, Eval

from .editor import get_editor_url, is_editable_filename


class Attachment(metaclass=PoolMeta):
    __name__ = 'ir.attachment'

    collabora_url = fields.Function(
        fields.Char('Open', states={
                'invisible': ~Bool(Eval('collabora_url')),
                }),
        'get_collabora_url')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
                'open': {
                    'invisible': ~Bool(Eval('collabora_url')),
                    'depends': ['collabora_url'],
                    },
                })

    @classmethod
    def get_collabora_url(cls, attachments, name):
        return {
            attachment.id: (
                get_editor_url(cls.__name__, attachment.id, 'data',
                    attachment.name)
                if attachment.type == 'data'
                and is_editable_filename(attachment.name) else None)
            for attachment in attachments}

    @classmethod
    @ModelView.button
    def open(cls, attachments):
        if not attachments:
            return
        attachment, = attachments
        return {
            'type': 'ir.action.url',
            'url': attachment.collabora_url,
            }
