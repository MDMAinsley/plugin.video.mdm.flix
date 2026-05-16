from resources.lib.kodi_addons import is_addon_installed
from resources.lib.providers.base import BaseProvider


class CocoScrapersProvider(BaseProvider):
    provider_id = "cocoscrapers"
    name = "CocoScrapers"
    addon_id = "script.module.cocoscrapers"

    def is_available(self):
        return is_addon_installed(self.addon_id)

    def search_sources(self, item):
        # Real CocoScrapers integration comes later.
        return []

    def resolve_source(self, source):
        return source.get("url")