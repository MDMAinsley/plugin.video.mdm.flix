import xbmc
import xbmcgui
from mdmlink import API_VERSION
from mdmlink import api
from resources.lib.kodi_addons import get_addon
from resources.lib.playback.errors import PlaybackError

class MDMLinkProvider:
    provider_id='mdm_link'
    name='MDM Link'
    addon_id='script.mdm.link'

    def __init__(self,addon=None,core=None,log=None):
        self.addon=get_addon(self.addon_id)
        if API_VERSION!=1: raise PlaybackError('MDM Link API is incompatible. Update Link and Flix together.')
        if self.addon and addon: api.migrate(self.addon,addon)

    def is_available(self): return self.addon is not None

    def configured(self):
        if not self.addon: raise PlaybackError('Install and enable MDM Link, then search again.')
        api.configured(self.addon)

    def search_sources(self,item):
        self.configured()
        progress=xbmcgui.DialogProgress(); progress.create('MDM Link','Searching enabled providers…')
        monitor=xbmc.Monitor()
        try:
            rows=api.search(self.addon,item,lambda:progress.iscanceled() or monitor.abortRequested(),progress.update)
            status=api.status(self.addon)
            failures=[s for s in status['last_search'] if s['status']!='ok']
            if failures and rows: xbmcgui.Dialog().notification('MDM Link','Some providers failed or timed out; showing available results.',xbmcgui.NOTIFICATION_INFO,3000)
            return rows
        finally: progress.close()

    def resolve_source(self,source,addon=None,progress=None,monitor=None,choose=None):
        self.configured()
        return api.resolve(self.addon,source,progress,monitor,choose,policy_addon=addon)
