class BaseProvider:
    provider_id = None
    name = None

    def __init__(self, core=None, log=None):
        self.core = core
        self.log = log

    def is_available(self):
        return False

    def search_sources(self, item):
        raise NotImplementedError

    def resolve_source(self, source):
        raise NotImplementedError