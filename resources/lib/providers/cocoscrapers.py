from resources.lib.providers.base import BaseProvider


class CocoScrapersProvider(BaseProvider):
    provider_id = "cocoscrapers"
    name = "CocoScrapers"

    def is_available(self):
        # Placeholder. Later this should detect the real CocoScrapers addon/API.
        return False

    def search_sources(self, item):
        return []

    def resolve_source(self, source):
        return source.get("url")