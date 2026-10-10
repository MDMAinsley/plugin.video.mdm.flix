import xbmc
import xbmcgui
from resources.lib.catalogue.tmdb import CatalogueError
from resources.lib.catalogue.playback_item import load
from resources.lib.playback.alldebrid import AllDebrid
from resources.lib.playback.errors import PlaybackError, Cancelled
from resources.lib.playback.selection import sort_sources
from resources.lib.playback.player import play_url, failed
from resources.lib.providers.manager import ProviderManager
from resources.lib.session import store_sources, get_source


def configured(addon):
    ProviderManager(addon).configured()


def search(addon,core,log,params):
    configured(addon)
    item=load(addon,core,params)
    return sort_sources(ProviderManager(addon,core,log).search_sources(item))


def show_sources(nav,addon,core,log,params):
    try:
        rows=search(addon,core,log,params)
        if not rows:
            xbmcgui.Dialog().ok('MDM Flix','No sources found. Try another title or check enabled providers and source mode.')
            nav.end(); return
        saved=store_sources(rows)
        for source_id,source in saved.items():
            size=source.get('size')
            size=' · {:.2f} GB'.format(size) if type(size) in (int,float) and size>0 else ''
            access='AllDebrid · unchecked' if source.get('debrid') else 'Free · direct'
            label='[{}] {}{} · {}'.format(access,source.get('quality','Unknown'),size,source['label'])
            note='AllDebrid availability is checked when selected.' if source.get('debrid') else 'Direct free source; availability depends on the source host.'
            nav.add_playable(label,'play',params={'source_id':source_id},info={'plot':'{}\n{}'.format(source['provider_name'],note)})
        nav.end('videos')
    except Cancelled:
        nav.end()
    except (PlaybackError,CatalogueError) as failure:
        xbmcgui.Dialog().ok('MDM Flix',str(failure))
        nav.add_action('Open settings','open_settings'); nav.end()
    except Exception:
        if log: log.warning('Source search failed unexpectedly')
        xbmcgui.Dialog().ok('MDM Flix','Source search failed. Check providers/settings and try again.')
        nav.end()


def resolve(source,addon,core,log):
    progress=xbmcgui.DialogProgress(); progress.create('MDM Flix','Resolving the selected source…')
    monitor=xbmc.Monitor()
    try:
        def choose(names):
            # Avoid modal selection being hidden behind the progress window.
            progress.close()
            choice=xbmcgui.Dialog().select('Choose matching video file',names)
            if choice>=0: progress.create('MDM Flix','Resolving selected video…')
            return choice
        return ProviderManager(addon,core,log).resolve_source(source,progress,monitor,choose)
    finally:
        progress.close()


def play_source(source_id,addon,core,log):
    try:
        source=get_source(source_id)
        if not source: raise PlaybackError('Source session expired or was replaced. Open sources again.')
        url=resolve(source,addon,core,log)
        play_url(url,source.get('label','MDM Flix'))
    except Cancelled:
        failed()
    except (PlaybackError,CatalogueError) as failure:
        xbmcgui.Dialog().ok('MDM Flix',str(failure)); failed()
    except Exception:
        if log: log.warning('Playback resolution failed unexpectedly')
        xbmcgui.Dialog().ok('MDM Flix','Playback resolution failed. Search again or try another source.'); failed()


def autoplay(nav,addon,core,log,params):
    try:
        rows=search(addon,core,log,params)
        if not rows: raise PlaybackError('No sources found. Try another title or check provider settings/source mode.')
        # Resolve only the top candidate, so autoplay never creates bulk transfers.
        url=resolve(rows[0],addon,core,log)
        play_url(url,rows[0]['label'])
    except Cancelled:
        failed()
    except (PlaybackError,CatalogueError) as failure:
        xbmcgui.Dialog().ok('MDM Flix',str(failure)); failed()
    except Exception:
        if log: log.warning('Autoplay failed unexpectedly')
        xbmcgui.Dialog().ok('MDM Flix','Autoplay failed. Try Source Select or another title.'); failed()
