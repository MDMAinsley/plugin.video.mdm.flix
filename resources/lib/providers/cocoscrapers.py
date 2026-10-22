"""Adapter for installed CocoScrapers sources(data, hostDict)."""
from resources.lib import device_policy,connection_policy
import copy
import hashlib
import os
import queue
import re
import sys
import threading
import time
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from resources.lib.kodi_addons import is_addon_installed
from resources.lib.providers.base import BaseProvider
from resources.lib.playback.errors import PlaybackError, Cancelled


class CocoScrapersProvider(BaseProvider):
    provider_id = 'cocoscrapers'
    name = 'CocoScrapers'
    addon_id = 'script.module.cocoscrapers'

    def __init__(self,addon=None,core=None,log=None):
        super().__init__(core,log);self.addon=addon or xbmcaddon.Addon("plugin.video.mdm.flix")

    def is_available(self):
        return is_addon_installed(self.addon_id)

    @staticmethod
    def modules():
        if not is_addon_installed('script.module.cocoscrapers'):
            raise PlaybackError('Install and enable CocoScrapers from its repository, then search again.')
        addon = xbmcaddon.Addon('script.module.cocoscrapers')
        library = xbmcvfs.translatePath(os.path.join(addon.getAddonInfo('path'),'lib'))
        if library not in sys.path:
            sys.path.append(library)
        try:
            from cocoscrapers import sources
            modules = sources(specified_folders=['torrents'])
        except Exception:
            raise PlaybackError('CocoScrapers could not load. Enable/update it and check its provider settings.') from None
        modules = [(name,cls) for name,cls in modules if isinstance(name,str) and callable(cls)]
        if not modules:
            raise PlaybackError('No CocoScrapers torrent providers are enabled. Open Provider Settings and enable providers.')
        return modules

    @staticmethod
    def data(item):
        data = {'title':item['title'], 'year':str(item['year']), 'imdb':item['imdb_id'], 'aliases':item.get('extra',{}).get('aliases',[])}
        if item['media_type']=='episode':
            data.update(tvshowtitle=item['tvshowtitle'],season=str(item['season']),episode=str(item['episode']))
        return data

    @staticmethod
    def convert(raw, name, item):
        if not isinstance(raw,dict): return None
        url = raw.get('url')
        if not isinstance(url,str) or not url.startswith('magnet:') or any(c in url for c in ('\r','\n','\x00')): return None
        match = re.search(r'(?:[?&])xt=urn:btih:([A-Za-z0-9]+)(?:&|$)',url,re.I)
        if not match or not (re.fullmatch(r'[0-9a-fA-F]{40}',match[1]) or re.fullmatch(r'[A-Z2-7]{32}',match[1],re.I)): return None
        label = raw.get('name') or raw.get('label') or name
        if not isinstance(label,str): label = name
        return {'source_id':hashlib.sha256(url.encode()).hexdigest(), 'label':label[:240], 'url':url,
                'provider_id':'cocoscrapers', 'provider_name':'CocoScrapers / '+name,
                'quality':raw.get('quality') if isinstance(raw.get('quality'),str) else 'Unknown',
                'size':connection_policy.coco_size(raw.get('size')) or '', 'host':'torrent', 'debrid':True,
                'extra':{'item':item, 'size_scope':'package' if raw.get('package') else 'file' if item.get('media_type')=='movie' or 'package' in raw else 'unknown', 'hash':match[1].lower(), 'scraper':name, 'availability':'unchecked', **({'has_chapters':raw['has_chapters']} if type(raw.get('has_chapters')) is bool else {})}}

    def search_sources(self, item):
        modules = self.modules()
        jobs, results = queue.Queue(), queue.Queue()
        stop = threading.Event()
        data = self.data(item)
        for module in modules: jobs.put(module)
        def worker():
            while not stop.is_set():
                try: name, factory = jobs.get_nowait()
                except queue.Empty: return
                rows=[]
                try:
                    scraper=factory()
                    supported=getattr(scraper,'hasEpisodes' if item['media_type']=='episode' else 'hasMovies',True)
                    if supported: rows=scraper.sources(copy.deepcopy(data), {})
                except Exception:
                    if self.log: self.log.warning('A CocoScrapers provider failed during search')
                results.put((name,rows))
        progress=xbmcgui.DialogProgress(); progress.create('MDM Flix','Searching enabled CocoScrapers providers…')
        monitor=xbmc.Monitor()
        for _ in range(min(device_policy.integer(self.addon,"device_workers",6,1,6),len(modules))): threading.Thread(target=worker,daemon=True).start()
        completed=0; found=[]; seen=set(); deadline=time.monotonic()+device_policy.integer(self.addon,"device_search_timeout",45,10,120)
        try:
            while completed<len(modules) and time.monotonic()<deadline:
                if progress.iscanceled() or monitor.abortRequested(): raise Cancelled('Source search cancelled.')
                try: name,rows=results.get(timeout=0.1)
                except queue.Empty: continue
                completed+=1
                for raw in rows if isinstance(rows,list) else []:
                    source=self.convert(raw,name,item)
                    if source and device_policy.allows(self.addon,source) and connection_policy.allows(self.addon,source) and source['extra']['hash'] not in seen:
                        found.append(source); seen.add(source['extra']['hash'])
                progress.update(int(100*completed/len(modules)), '{} providers finished · {} sources'.format(completed,len(found)))
            if completed<len(modules): xbmcgui.Dialog().notification('MDM Flix','Search timed out; showing completed provider results.',xbmcgui.NOTIFICATION_INFO,3000)
        finally:
            stop.set(); progress.close()
        return found

    def resolve_source(self, source, addon=None, progress=None, monitor=None, choose=None):
        from resources.lib.playback.alldebrid import AllDebrid
        return AllDebrid(addon).resolve(source,progress,monitor,choose)
