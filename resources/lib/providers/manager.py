from resources.lib.constants import (
    PROVIDER_AUTO,
    PROVIDER_MDM_LINK,
    PROVIDER_COCOSCRAPERS,
)

from resources.lib.providers.mdm_link import MDMLinkProvider
from resources.lib.providers.cocoscrapers import CocoScrapersProvider


class ProviderManager:
    def __init__(self, addon, core=None, log=None):
        self.addon = addon
        self.core = core
        self.log = log

    def get_setting_provider(self):
        raw = self.addon.getSetting("scraper_provider")

        if raw == "MDM Link":
            return PROVIDER_MDM_LINK

        if raw == "CocoScrapers":
            return PROVIDER_COCOSCRAPERS

        return PROVIDER_AUTO

    def get_provider(self):
        selected = self.get_setting_provider()

        mdm_link = MDMLinkProvider(core=self.core, log=self.log)
        cocoscrapers = CocoScrapersProvider(core=self.core, log=self.log)

        if selected == PROVIDER_MDM_LINK:
            return mdm_link

        if selected == PROVIDER_COCOSCRAPERS:
            return cocoscrapers

        # Auto mode.
        if mdm_link.is_available():
            return mdm_link

        if cocoscrapers.is_available():
            return cocoscrapers

        # Temporary development fallback.
        # This lets us test the architecture before script.mdm.link exists properly.
        return mdm_link

    def search_sources(self, item):
        provider = self.get_provider()

        if self.log:
            self.log.info(f"Using provider: {provider.name}")

        return provider.search_sources(item)

    def resolve_source(self, source):
        provider_id = source.get("provider_id")
        provider = self.get_provider()
        return provider.resolve_source(source)