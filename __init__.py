from trytond.pool import Pool

from . import attachment, lock, routes

__all__ = ['register', 'routes']


def register():
    Pool.register(
        attachment.Attachment,
        lock.WopiLock,
        module='collabora_online', type_='model')
