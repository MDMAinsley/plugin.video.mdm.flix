import xbmc
import time
import xbmcgui
from resources.lib import connection_policy
from resources.lib.catalogue.tmdb import CatalogueError
from resources.lib.catalogue.playback_item import load
from resources.lib.playback.alldebrid import AllDebrid
from resources.lib.playback.errors import PlaybackError, Cancelled
from resources.lib.playback.selection import sort_sources
from resources.lib.playback.player import play_url, failed
from resources.lib.providers.manager import ProviderManager
from resources.lib.session import store_sources, get_source, get_sources


def configured(addon):
    ProviderManager(addon).configured()


def search(addon,core,log,params):
    configured(addon)
    item=load(addon,core,params)
    from resources.lib.playback.timing_service import enqueue
    enqueue(addon,item)
    rows=ProviderManager(addon,core,log).search_sources(item)
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
    if params.get('refresh')=='1':
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
    try:
        started=time.monotonic()
        rows=search(addon,core,log,params)
        from resources.lib.playback.timing_match import enabled
        from resources.lib.playback.timing_rules import identity
        if enabled(addon) and rows and identity((rows[0].get('extra') or {}).get('item')):
            from resources.lib.playback.stream_match import compare
            monitor=xbmc.Monitor()
            compare(addon,rows,lambda source,attempt:resolve(source,addon,core,log,attempt),monitor.abortRequested,search_seconds=time.monotonic()-started)
            rows=sort_sources(rows,addon)
        if not rows:
            xbmcgui.Dialog().ok('MDM Flix','No sources remain. Check quality, file-size and connection preferences, enabled providers and source mode.')
            nav.end(); return
        saved=store_sources(rows)
        debrid=sum(bool(s.get('debrid')) for s in saved.values())
        free=len(saved)-debrid
        if debrid and free:
            anchor=next(iter(saved))
            for label,group in (('AllDebrid sources ({})'.format(debrid),'debrid'),('Free sources ({})'.format(free),'free'),('All sources ({})'.format(len(saved)),'all')):
                nav.add_folder(label,'source_group',params={'group':group,'anchor':anchor})
            nav.end('videos')
        else:
            if debrid and addon.getSetting('scraper_provider')=='MDM Link':
                xbmcgui.Dialog().notification('MDM Flix','{} AllDebrid sources; no free matches returned for this search.'.format(debrid),xbmcgui.NOTIFICATION_INFO,5000)
            display_sources(nav,saved,addon)
    except Cancelled:
        nav.end()
    except (PlaybackError,CatalogueError) as failure:
        xbmcgui.Dialog().ok('MDM Flix',str(failure))
        nav.add_action('Open settings','open_settings'); nav.end()
    except Exception:
        if log: log.warning('Source search failed unexpectedly')
        xbmcgui.Dialog().ok('MDM Flix','Source search failed. Check providers/settings and try again.')
        nav.end()


def display_sources(nav,saved,addon=None):
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
        if item.get('media_type')=='episode':
            from urllib.parse import urlencode
            query=urlencode(dict(action='sources',media_type='tv',tmdb_id=item['tmdb_id'],season=item['season'],episode=item['episode'],refresh='1'))
            context=[('Refresh sources and timings','ActivateWindow(Videos,plugin://plugin.video.mdm.flix/?'+query+',return)'),('Timing match report','RunPlugin(plugin://plugin.video.mdm.flix/?action=matching_report)')]
        nav.add_playable(label,'play',params={'source_id':source_id},info={'plot':'{}\n{}'.format(source['provider_name'],note)},context_menu=context)
    nav.end('videos')


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
