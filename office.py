from trytond.pool import PoolMeta
from trytond.wizard import StateAction


class DocumentCreate(metaclass=PoolMeta):
    __name__ = 'office.document.create'

    open_collabora = StateAction(
        'collabora_online.action_open_office_document')

    def transition_create_(self):
        state = super().transition_create_()
        if state == 'end' and self.attachment.collabora_url:
            return 'open_collabora'
        return state

    def transition_open_(self):
        if self.attachment.collabora_url:
            return 'open_collabora'
        return 'end'

    def do_open_collabora(self, action):
        action['url'] = self.attachment.collabora_url
        return action, {}
