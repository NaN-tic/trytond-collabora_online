from trytond.pool import Pool

from . import attachment, lease, lock, routes

__all__ = ['register', 'routes']


def register():
    Pool.register(
        attachment.Attachment,
        lease.WopiLease,
        lock.WopiLock,
        module='collabora_online', type_='model')
