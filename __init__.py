from trytond.pool import Pool

from . import attachment, lease, lock, office, routes

__all__ = ['register', 'routes']


def register():
    Pool.register(
        attachment.Attachment,
        lease.WopiLease,
        lock.WopiLock,
        module='collabora_online', type_='model')
    Pool.register(
        office.DocumentCreate,
        module='collabora_online', type_='wizard', depends=['office'])
