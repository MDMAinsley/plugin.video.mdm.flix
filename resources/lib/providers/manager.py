from resources.lib.providers.cocoscrapers import CocoScrapersProvider
from resources.lib.models.source import normalise_sources
from resources.lib.playback.errors import PlaybackError


class ProviderManager:
    def __init__(self, addon, core=None, log=None):
        self.addon, self.core, self.log = addon, core, log

    def get_provider(self):
        if self.addon.getSetting('scraper_provider')=='MDM Link':
            raise PlaybackError('MDM Link integration is planned for a later batch. Select Auto or CocoScrapers in settings.')
        provider=CocoScrapersProvider(core=self.core,log=self.log)
        if not provider.is_available(): raise PlaybackError('Install and enable CocoScrapers, then search again.')
        return provider

    def search_sources(self, item):
        provider=self.get_provider()
        return normalise_sources(provider.search_sources(item),provider.provider_id,provider.name)

    def resolve_source(self, source, progress, monitor, choose):
        # Respect the original provider even when Auto/settings change.
        if source.get('provider_id')!='cocoscrapers': raise PlaybackError('This source uses an unavailable provider. Search again.')
        provider=CocoScrapersProvider(core=self.core,log=self.log)
        if not provider.is_available(): raise PlaybackError('CocoScrapers is unavailable. Enable it and search again.')
        return provider.resolve_source(source,addon=self.addon,progress=progress,monitor=monitor,choose=choose)
