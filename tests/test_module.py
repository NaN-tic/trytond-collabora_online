from trytond.tests.test_tryton import ModuleTestCase


class CollaboraOnlineTestCase(ModuleTestCase):
    'Test Collabora Online module'
    module = 'collabora_online'
    extras = ['papyrus']


del ModuleTestCase
