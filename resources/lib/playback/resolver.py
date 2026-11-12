import json
import xbmc
import time
import xbmcgui
from resources.lib import connection_policy
from resources.lib.catalogue.tmdb import CatalogueError
from resources.lib.catalogue.playback_item import load
from resources.lib.playback.alldebrid import AllDebrid
from resources.lib.playback.errors import PlaybackError, Cancelled
from resources.lib.playback.selection import sort_sources
from resources.lib.playback import scrape_cache
from resources.lib.playback.player import play_url, failed
from resources.lib.providers.manager import ProviderManager, auto
from resources.lib.session import store_sources, get_source, get_sources


SEARCH_DIAGNOSTICS = 'MDM.Flix.LatestScraperSearch'


def latest_search():
    try:
        raw = xbmcgui.Window(10000).getProperty(SEARCH_DIAGNOSTICS)
        value = json.loads(raw) if raw and len(raw) <= 4096 else {}
        return value if isinstance(value, dict) else {}
    except (AttributeError, RuntimeError, ValueError):
        return {}


def configured(addon):
    ProviderManager(addon).configured()


def search(addon,core,log,params,*,fallback_item=None):
    configured(addon)
    fallback = fallback_item is not None
    item = fallback_item if fallback else load(addon,core,params)
    from resources.lib.playback.timing_service import enqueue
    if not fallback:
        enqueue(addon,item)
    cache_key = scrape_cache.key(addon,item,fallback=True) if fallback else scrape_cache.key(addon,item)
    if not fallback and auto(addon) and params.get('refresh') == '1':
        scrape_cache.forget(scrape_cache.key(addon,item,fallback=True))
    refresh=params.get('refresh')=='1'
    if refresh:scrape_cache.forget(cache_key)
    rows=None if refresh else scrape_cache.get(cache_key)
    params['_scrape_cache_hit']=rows is not None
    if rows is None:
        manager = ProviderManager(addon,core,log)
        try:
            rows = manager.search_sources(item,fallback=True) if fallback else manager.search_sources(item)
        finally:
            if isinstance(manager.search_report, dict):
                report = latest_search() if fallback else {}
                report.update(manager.search_report)
                try:
                    xbmcgui.Window(10000).setProperty(SEARCH_DIAGNOSTICS, json.dumps(report))
                except (AttributeError, RuntimeError):
                    pass
        # Recheck Link on the next search when a temporary failure sent Auto to Coco.
        cacheable = fallback or not auto(addon) or any(row.get('provider_id') == 'mdm_link' for row in rows)
        if cacheable and not xbmc.Monitor().abortRequested():
            scrape_cache.put(cache_key,rows)
    for row in rows:
        row['extra']=dict(row.get('extra') or {})
        row['extra']['item']=item
        row['_progress_mode']=params.get('resume_mode') if params.get('resume_mode') in ('resume','restart') else ''
    from resources.lib.playback.media_metadata import search_candidates
    monitor=xbmc.Monitor()
    from resources.lib.playback.timing_match import enabled
    rows=sort_sources(rows,addon)
    if not enabled(addon):rows=search_candidates(addon,rows,monitor.abortRequested)
    if monitor.abortRequested():raise Cancelled("Playback cancelled.")
    if refresh:
        from resources.lib.playback.media_metadata import Cache
        from resources.lib.playback.chapter_facts import fingerprint
        from resources.lib.playback.timing_store import Store,TimingError
        from resources.lib.playback.timing_rules import identity
        keys=[fingerprint(row) for row in rows]
        Cache(addon).forget_many(keys)
        try:Store(addon).refresh(identity(item),keys)
        except TimingError:pass
        for row in rows:
            extra=dict(row.get('extra') or {})
            if extra.get('file_duration_origin') in ('header','observed'):
                extra.pop('file_duration_seconds',None);extra.pop('file_duration_origin',None)
            row['extra']=extra
    return sort_sources(rows,addon)


def show_sources(nav,addon,core,log,params):
    cache = params.get('refresh') != '1'
    try:
        # Browsing a list must never queue debrid transfers. Existing metadata
        # still informs sorting; actual preparation starts after selection.
        rows=search(addon,core,log,dict(params))
        if not rows:
            xbmcgui.Dialog().ok('MDM Flix','No sources remain. Check quality, file-size and connection preferences, enabled providers and source mode.')
            nav.end(cache=cache); return
        saved=store_sources(rows)
        debrid=sum(bool(s.get('debrid')) for s in saved.values())
        free=len(saved)-debrid
        if debrid and free:
            anchor=next(iter(saved))
            for label,group in (('AllDebrid sources ({})'.format(debrid),'debrid'),('Free sources ({})'.format(free),'free'),('All sources ({})'.format(len(saved)),'all')):
                nav.add_folder(label,'source_group',params={'group':group,'anchor':anchor})
            nav.end('videos', cache=cache)
        else:
            if debrid and addon.getSetting('scraper_provider')=='MDM Link':
                xbmcgui.Dialog().notification('MDM Flix','{} AllDebrid sources; no free matches returned for this search.'.format(debrid),xbmcgui.NOTIFICATION_INFO,5000)
            display_sources(nav,saved,addon,cache=cache)
    except Cancelled:
        nav.end(cache=cache)
    except (PlaybackError,CatalogueError) as failure:
        xbmcgui.Dialog().ok('MDM Flix',str(failure))
        nav.add_action('Open settings','open_settings'); nav.end(cache=cache)
    except Exception:
        if log: log.warning('Source search failed unexpectedly')
        xbmcgui.Dialog().ok('MDM Flix','Source search failed. Check providers/settings and try again.')
        nav.end(cache=cache)


def display_sources(nav,saved,addon=None,*,cache=True):
    for source_id,source in saved.items():
        size=source.get('size')
        size=' · {:.2f} GiB'.format(size) if type(size) in (int,float) and size>0 else ''
        access='AllDebrid · unchecked' if source.get('debrid') else 'Free · direct'
        label='[{}] {}{} · {}'.format(access,source.get('quality','Unknown'),size,source['label'])
        if addon is not None:label+=connection_policy.badge(addon,source)
        note='AllDebrid availability is checked when selected.' if source.get('debrid') else 'Direct free source; availability depends on the source host.'
        if addon is not None:note+='\n'+connection_policy.note(addon,source)
        context=[]
        item=(source.get('extra') or {}).get('item') or {}
        if item.get('media_type') in ('episode','movie'):
            from urllib.parse import urlencode
            episode=item['media_type']=='episode'
            params=dict(action='sources',media_type='tv' if episode else 'movie',tmdb_id=item['tmdb_id'],refresh='1')
            if episode:params.update(season=item['season'],episode=item['episode'])
            query=urlencode(params)
            context=[('Refresh sources and timings' if episode else 'Refresh sources','ActivateWindow(Videos,plugin://plugin.video.mdm.flix/?'+query+',return)')]
            if episode:context.append(('Timing match report','RunPlugin(plugin://plugin.video.mdm.flix/?action=matching_report)'))
        nav.add_playable(label,'play',params={'source_id':source_id},info={'plot':'{}\n{}'.format(source['provider_name'],note)},context_menu=context)
    nav.end('videos', cache=cache)


def show_group(nav,params):
    group=params.get('group')
    saved=get_sources(params.get('anchor'))
    if group not in ('all','free','debrid') or not saved:
        xbmcgui.Dialog().ok('MDM Flix','This source list expired or was replaced. Open sources again.')
        nav.end();return
    import xbmcaddon
    addon=xbmcaddon.Addon('plugin.video.mdm.flix')
    ordered=sort_sources(list(saved.values()),addon)
    saved={source['source_id']:source for source in ordered}
    rows={key:source for key,source in saved.items() if group=='all' or bool(source.get('debrid'))==(group=='debrid')}
    display_sources(nav,rows,addon)


def resolve(source,addon,core,log,attempt=None):
    progress=xbmcgui.DialogProgress(); progress.create('MDM Flix',('Trying source {} of {}…'.format(*attempt) if attempt else 'Resolving the selected source…'))
    monitor=xbmc.Monitor()
    try:
        def choose(names):
            # Avoid modal selection being hidden behind the progress window.
            progress.close()
            choice=xbmcgui.Dialog().select('Choose matching video file',names)
            if choice>=0: progress.create('MDM Flix','Resolving selected video…')
            return choice
        url=ProviderManager(addon,core,log).resolve_source(source,progress,monitor,choose)
        from resources.lib.playback.media_metadata import prepare
        from mdmlink import autoplay_context
        autoplay_context.check()
        remaining=autoplay_context.remaining()
        budget=min(4,remaining) if remaining is not None else 4
        if budget>.1:
            progress.update(95,'Checking video duration and chapter metadata…')
            prepare(addon,source,url,budget,lambda:progress.iscanceled() or monitor.abortRequested())
        if progress.iscanceled() or monitor.abortRequested():raise Cancelled('Playback cancelled.')
        return url
    except Exception:
        if progress.iscanceled() or monitor.abortRequested():
            raise Cancelled('Playback cancelled.') from None
        raise
    finally:
        progress.close()


def play_source(source_id,addon,core,log):
    try:
        source=get_source(source_id)
        if not source: raise PlaybackError('Source session expired or was replaced. Open sources again.')
        url=resolve(source,addon,core,log)
        from resources.lib.playback.tracking import source as tracking_source
        with tracking_source(source,addon):
            play_url(url,source.get('label','MDM Flix'))
    except Cancelled:
        failed()
    except (PlaybackError,CatalogueError) as failure:
        xbmcgui.Dialog().ok('MDM Flix',str(failure)); failed()
    except Exception:
        if log: log.warning('Playback resolution failed unexpectedly')
        xbmcgui.Dialog().ok('MDM Flix','Playback resolution failed. Search again or try another source.'); failed()


def autoplay(nav,addon,core,log,params):
    from resources.lib.playback.autoplay import run
    run(nav,addon,core,log,params,search,resolve,play_url,failed)
