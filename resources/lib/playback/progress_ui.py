"""Visible viewing actions, shared by Basic and Artwork home navigation."""
from contextlib import nullcontext
import time
import xbmc
import xbmcgui
from resources.lib.playback.progress import ProgressError,clean
from resources.lib.playback.viewing import Viewing
from resources.lib.mdblist_account import State, MDBError
from resources.lib.library_store import Library,LibraryError,identity
from resources.lib.catalogue.tmdb import TMDB,CatalogueError

def identity_params(item):
    result={'media_type':item['media_type'],'tmdb_id':item['tmdb_id']}
    if item['media_type']=='episode':result.update(season=item['season'],episode=item['episode'])
    return result

def requested(params):
    kind='episode' if params.get('media_type') in ('tv','episode') else params.get('media_type')
    return clean(dict(params,media_type=kind,title='MDM title'))

def title_identity(params):
    if params.get('media_type')=='tv' and 'season' not in params and 'episode' not in params:
        media,identifier=identity('tv',params.get('tmdb_id'))
        return dict(media_type=media,tmdb_id=identifier)
    return requested(params)

def play_entry(nav,addon,label,item,mode,**metadata):
    params=dict(identity_params(item),resume_mode=mode)
    if addon.getSetting('playback_mode')=='Autoplay':nav.add_playable(label,'autoplay',params=params,**metadata)
    else:nav.add_folder(label,'sources',params=params,**metadata)

def title_metadata(addon,core,item,row):
    if row:
        saved=row['item']
        return dict(artwork=saved['artwork'],info={
            'title':label(saved),'plot':saved['plot'],'mediatype':saved['media_type']})
    if core is None:
        return {}
    from resources.lib.catalogue.browse import artwork,info
    client=TMDB(addon,core)
    if not client.configured:
        return {}
    media=item['media_type'];identifier=item['tmdb_id']
    try:
        if media=='episode':
            raw=client.request('tv/{}/season/{}/episode/{}'.format(identifier,item['season'],item['episode']),ttl=3600)
        else:
            raw=client.details(media,identifier)
        kind='tvshow' if media=='tv' else media
        return dict(artwork=artwork(raw,addon=addon),info=info(raw,kind))
    except CatalogueError:
        return {}

def label(item):
    if item['media_type']=='episode':return '{} · S{:02d}E{:02d} · {}'.format(item['tvshowtitle'] or 'TV',item['season'],item['episode'],item['title'])
    return item['title']

def show(nav,addon,core,params):
    try:
        store=Viewing(addon)
        if params.get('action') in ('continue_watching','viewing_history'):
            continuing=params['action']=='continue_watching'
            rows=store.rows(continuing)
            for row in rows:
                item=row['item'];at=int(row['position'])
                text=label(item)+(' · Watched' if row['watched'] else ' · {}:{:02d}'.format(at//60,at%60))
                nav.add_folder(text,'progress_details',params=identity_params(item),artwork=item['artwork'],info={'title':item['title'],'plot':item['plot'],'mediatype':item['media_type']})
            if not rows:nav.add_action('Nothing here yet — progress appears after watching for at least 30 seconds.','progress_help')
            nav.end('videos');return
        item=title_identity(params)
        show_level=item['media_type']=='tv'
        row=None if show_level else store.get(item)
        at=int(row['position']) if row else 0
        common=identity_params(item)
        metadata=title_metadata(addon,core,item,row)
        nav.category(metadata.get('info',{}).get('title') or 'Title actions')
        if show_level:
            nav.add_folder('Browse episodes','tv_seasons',params=common,**metadata)
        else:
            if addon.getSetting('progress_enabled')!='false' and at>=30:
                play_entry(nav,addon,'Resume from {}:{:02d}'.format(at//60,at%60),item,'resume',**metadata)
            play_entry(nav,addon,'Start again' if at or row and row['watched'] else 'Play',item,'restart',**metadata)
        try:
            media='movie' if item['media_type']=='movie' else 'tv'
            saved=any(membership['id']==1 for membership in Library(addon).memberships(media,item['tmdb_id']))
        except LibraryError:
            saved=False
        nav.add_action('Remove from My List' if saved else 'Save to My List','progress_unsave' if saved else 'progress_save',params=common,**metadata)
        nav.add_action('Lists and rating','progress_lists',params=common,**metadata)
        if row:
            nav.add_action('Mark unwatched' if row['watched'] else 'Mark watched','progress_mark',
                           params=dict(common,watched='false' if row['watched'] else 'true'),**metadata)
            nav.add_action('Clear viewing record…','progress_clear',params=common,**metadata)
        nav.end('videos')
    except (ProgressError,LibraryError) as error:
        xbmcgui.Dialog().ok('Title actions',str(error));nav.end()

def action(addon,core,params):
    try:
        if params.get('action')=='progress_help':
            xbmcgui.Dialog().ok('Continue Watching','Progress is saved on this device after MDM video starts. Watch at least 30 seconds, then stop. Open MDBList in Flix to manage optional progress uploads.');return
        operation=params.get('action')
        if operation in ('progress_mark','progress_clear'):
            item=requested(params)
            viewing=Viewing(addon);store=viewing.local;row=viewing.get(item)
            if not row:raise ProgressError('No viewing record remains for this title.')
            item=row['item']
            account=viewing.account or {}
            scope=account.get('sync_id')
            if scope and not account.get('history_sync'):
                raise ProgressError('Open MDBList and choose Enable watched sync to change viewing history across devices.')
            guard=State(addon).guard(account) if scope else nullcontext()
        if operation=='progress_mark':
            if params.get('watched') not in ('true','false'):raise ProgressError('Invalid watched action.')
            watched=params['watched']=='true'
            if scope and not watched and not xbmcgui.Dialog().yesno('Mark unwatched on MDBList?',
                    'This clears the watched flag for this title across linked devices.'):
                return
            edit=(scope,'watched' if watched else 'unwatched',time.time(),None) if scope else None
            with guard:
                store.save(item,0,row['duration'],watched,cancel_sync=True,action=edit)
        elif operation=='progress_clear':
            message=('Clear this title’s resume position and watched flag on MDBList and this device?' if scope else
                     'Remove this title’s saved position and watched state? Your lists and ratings are kept.')
            if not xbmcgui.Dialog().yesno('Clear viewing record?',message):return
            with guard:
                store.remove(item,action=(scope,'clear',time.time(),None) if scope else None)
        elif operation in ('progress_save','progress_unsave','progress_lists'):
            from resources.lib.library_ui import title_row,action as library_action
            item=title_identity(params)
            media='movie' if item['media_type']=='movie' else 'tv'
            if operation=='progress_lists':library_action(addon,core,dict(action='library_manage',media_type=media,tmdb_id=item['tmdb_id']));return
            library=Library(addon)
            if operation=='progress_unsave':library.remove(1,media,item['tmdb_id'])
            else:library.add(title_row(library,addon,core,media,item['tmdb_id']))
        else:raise ProgressError('Unknown viewing action.')
        queued=operation in ('progress_mark','progress_clear') and scope
        message='Saved locally and queued for MDBList.' if queued else 'Saved on this device.'
        xbmcgui.Dialog().notification('MDM Flix',message,xbmcgui.NOTIFICATION_INFO,2000);xbmc.executebuiltin('Container.Refresh')
    except (ProgressError,LibraryError,CatalogueError) as error:xbmcgui.Dialog().ok('Viewing progress',str(error))
    except MDBError:xbmcgui.Dialog().ok('Viewing progress','The MDBList connection changed. Open this title and try again.')
