from resources.lib.providers.cocoscrapers import CocoScrapersProvider
from resources.lib.providers.mdm_link import MDMLinkProvider
from resources.lib.models.source import normalise_sources
from resources.lib.playback.errors import PlaybackError


class ProviderManager:
    def __init__(self, addon, core=None, log=None):
        self.addon, self.core, self.log = addon, core, log

    def get_provider(self):
        if self.addon.getSetting('scraper_provider')=='MDM Link':
            provider=MDMLinkProvider(self.addon,core=self.core,log=self.log)
            if not provider.is_available(): raise PlaybackError('Install and enable MDM Link, then search again.')
            return provider
        provider=CocoScrapersProvider(core=self.core,log=self.log)
        if not provider.is_available(): raise PlaybackError('Install and enable CocoScrapers, then search again.')
        return provider

    def configured(self):
        if self.addon.getSetting('scraper_provider')=='MDM Link':
            self.get_provider().configured()
        else:
            from resources.lib.playback.alldebrid import AllDebrid
            client=AllDebrid(self.addon)
            if not client.enabled: raise PlaybackError('Enable AllDebrid in settings and authorise it in Tools.')
            if not client.key: raise PlaybackError('Authorise AllDebrid in Tools before searching sources.')

    def search_sources(self, item):
        provider=self.get_provider()
        return normalise_sources(provider.search_sources(item),provider.provider_id,provider.name)

    def resolve_source(self, source, progress, monitor, choose):
        # Respect the original provider even when Auto/settings change.
        if source.get('provider_id')=='mdm_link':
            return MDMLinkProvider(self.addon,core=self.core,log=self.log).resolve_source(source,addon=self.addon,progress=progress,monitor=monitor,choose=choose)
        if source.get('provider_id')!='cocoscrapers': raise PlaybackError('This source uses an unavailable provider. Search again.')
        provider=CocoScrapersProvider(core=self.core,log=self.log)
        if not provider.is_available(): raise PlaybackError('CocoScrapers is unavailable. Enable it and search again.')
        return provider.resolve_source(source,addon=self.addon,progress=progress,monitor=monitor,choose=choose)
