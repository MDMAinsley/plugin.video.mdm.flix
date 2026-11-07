from resources.lib import device_policy,connection_policy
from resources.lib.providers.cocoscrapers import CocoScrapersProvider
from resources.lib.providers.mdm_link import MDMLinkProvider
from resources.lib.models.source import normalise_sources
from resources.lib.playback.errors import PlaybackError, Cancelled
from resources.lib.playback.selection import usable
from mdmlink import api
from mdmlink.errors import AutoplayBudgetExpired


def auto(addon):
    return addon.getSetting('scraper_provider') in ('', 'Auto')


class ProviderManager:
    def __init__(self, addon, core=None, log=None):
        self.addon, self.core, self.log = addon, core, log
        self.search_report = {}

    def get_provider(self, name=None):
        if name is None:
            name = 'MDM Link' if auto(self.addon) else self.addon.getSetting('scraper_provider')
        if name == 'MDM Link':
            provider=MDMLinkProvider(self.addon,core=self.core,log=self.log)
            if not provider.is_available(): raise PlaybackError('Install and enable MDM Link, then search again.')
            return provider
        provider=CocoScrapersProvider(addon=self.addon,core=self.core,log=self.log)
        if not provider.is_available(): raise PlaybackError('Install and enable CocoScrapers, then search again.')
        return provider

    def preferences(self):
        try:connection_policy.validate_settings(self.addon)
        except ValueError as error:raise PlaybackError(str(error)) from None

    def configured(self):
        self.preferences()
        if not auto(self.addon):
            self._configured_provider(self.addon.getSetting('scraper_provider'))

    def _configured_provider(self, name):
        provider = self.get_provider(name)
        if name == 'MDM Link':
            provider.configured()
        else:
            from resources.lib.playback.alldebrid import AllDebrid
            client = AllDebrid(self.addon)
            if not client.enabled:
                raise PlaybackError('Enable AllDebrid in settings and authorise it in Tools.')
            if not client.key:
                raise PlaybackError('Authorise AllDebrid in Tools before searching sources.')
        return provider

    def _search(self, provider, item):
        status = self.search_report.setdefault(provider.provider_id, {})
        try:
            results = provider.search_sources(item)
        except (Cancelled, AutoplayBudgetExpired):
            status['result'] = 'cancelled or timed out'
            raise
        except PlaybackError:
            status['result'] = 'search failed'
            raise
        finally:
            if provider.provider_id == 'mdm_link' and isinstance(provider.search_report, dict):
                status.update(provider.search_report)
        rows = normalise_sources(results, provider.provider_id, provider.name)
        status['returned'] = len(rows)
        rows = device_policy.filter_rows(self.addon, [row for row in rows if usable(row)])
        rows = connection_policy.select(self.addon, rows)
        status['flix_eligible'] = len(rows)
        status['result'] = 'results' if rows else 'no eligible sources'
        return rows

    def _coco_fallback(self, item):
        from resources.lib.kodi_addons import get_addon
        link = get_addon('script.mdm.link')
        if (link and api.mode(link) == 'Free') or not item.get('imdb_id'):
            return []
        self.search_report['cocoscrapers'] = {'result': 'unavailable or needs authorisation'}
        return self._search(self._configured_provider('CocoScrapers'), item)

    def search_sources(self, item, fallback=False):
        self.preferences()
        if not auto(self.addon):
            return [] if fallback else self._search(self.get_provider(), item)
        if fallback:
            return self._coco_fallback(item)

        link_error = None
        self.search_report['mdm_link'] = {'result': 'unavailable'}
        try:
            rows = self._search(self.get_provider('MDM Link'), item)
            if rows:
                return rows
        except (Cancelled, AutoplayBudgetExpired):
            raise
        except PlaybackError as error:
            link_error = error

        try:
            rows = self._coco_fallback(item)
        except (Cancelled, AutoplayBudgetExpired):
            raise
        except PlaybackError:
            if link_error is not None:
                raise link_error from None
            return []
        if not rows and link_error is not None:
            raise link_error
        return rows

    def resolve_source(self, source, progress, monitor, choose):
        self.preferences()
        if not device_policy.allows(self.addon,source) or not connection_policy.allows(self.addon,source):raise PlaybackError("This source is excluded by your current quality, file-size or connection preferences. Search again or change Device settings.")
        # Respect the original provider even when Auto/settings change.
        if source.get('provider_id')=='mdm_link':
            return MDMLinkProvider(self.addon,core=self.core,log=self.log).resolve_source(source,addon=self.addon,progress=progress,monitor=monitor,choose=choose)
        if source.get('provider_id')!='cocoscrapers': raise PlaybackError('This source uses an unavailable provider. Search again.')
        provider=CocoScrapersProvider(addon=self.addon,core=self.core,log=self.log)
        if not provider.is_available(): raise PlaybackError('CocoScrapers is unavailable. Enable it and search again.')
        return provider.resolve_source(source,addon=self.addon,progress=progress,monitor=monitor,choose=choose)
