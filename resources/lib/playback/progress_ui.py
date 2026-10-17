"""Visible viewing actions, shared by Basic and Artwork home navigation."""
import xbmc
import xbmcgui
from resources.lib.playback.progress import Store,ProgressError,clean

def identity_params(item):
    result={'media_type':item['media_type'],'tmdb_id':item['tmdb_id']}
    if item['media_type']=='episode':result.update(season=item['season'],episode=item['episode'])
    return result

def requested(params):
    kind='episode' if params.get('media_type') in ('tv','episode') else params.get('media_type')
    return clean(dict(params,media_type=kind,title='MDM title'))

def play_entry(nav,addon,label,item,mode):
    params=dict(identity_params(item),resume_mode=mode)
    if addon.getSetting('playback_mode')=='Autoplay':nav.add_playable(label,'autoplay',params=params)
    else:nav.add_folder(label,'sources',params=params)

def label(item):
    if item['media_type']=='episode':return '{} · S{:02d}E{:02d} · {}'.format(item['tvshowtitle'] or 'TV',item['season'],item['episode'],item['title'])
    return item['title']

def show(nav,addon,core,params):
    try:
        store=Store(addon)
        if params.get('action') in ('continue_watching','viewing_history'):
            continuing=params['action']=='continue_watching'
            rows=store.rows(continuing)
            for row in rows:
                item=row['item'];at=int(row['position'])
                text=label(item)+(' · Watched' if row['watched'] else ' · {}:{:02d}'.format(at//60,at%60))
                nav.add_folder(text,'progress_details',params=identity_params(item),artwork=item['artwork'],info={'title':item['title'],'plot':item['plot'],'mediatype':item['media_type']})
            if not rows:nav.add_action('Nothing here yet — progress appears after watching for at least 30 seconds.','progress_help')
            nav.end('videos');return
        row=store.get(requested(params))
        if not row:
            xbmcgui.Dialog().ok('Viewing progress','No saved progress for this title yet.');nav.end();return
        item=row['item'];at=int(row['position']);common=identity_params(item)
        if not row['watched'] and at>=30:play_entry(nav,addon,'Resume from {}:{:02d}'.format(at//60,at%60),item,'resume')
        play_entry(nav,addon,'Start again' if at or row['watched'] else 'Play',item,'restart')
        nav.add_action('Mark unwatched' if row['watched'] else 'Mark watched','progress_mark',params=dict(common,watched='false' if row['watched'] else 'true'))
        from resources.lib.library_store import Library,LibraryError
        try:
            media='tv' if item['media_type']=='episode' else 'movie'
            saved=any(row['id']==1 for row in Library(addon).memberships(media,item['tmdb_id']))
        except LibraryError:saved=False
        nav.add_action('Remove from My List' if saved else 'Save to My List','progress_unsave' if saved else 'progress_save',params=common)
        nav.add_action('Lists / Your rating…','progress_lists',params=common)
        nav.add_action('Clear viewing record…','progress_clear',params=common)
        nav.end('videos')
    except ProgressError as error:xbmcgui.Dialog().ok('Viewing progress',str(error));nav.end()

def action(addon,core,params):
    from resources.lib.library_store import Library,LibraryError
    from resources.lib.catalogue.tmdb import CatalogueError
    try:
        if params.get('action')=='progress_help':
            xbmcgui.Dialog().ok('Continue Watching','Progress is saved on this device after MDM video starts. Watch at least 30 seconds, then stop. MDBList connection and cross-device sync are coming in the next tracking stage.');return
        item=requested(params);store=Store(addon);row=store.get(item)
        if not row:raise ProgressError('No viewing record remains for this title.')
        item=row['item'];operation=params.get('action')
        if operation=='progress_mark':
            if params.get('watched') not in ('true','false'):raise ProgressError('Invalid watched action.')
            store.save(item,0,row['duration'],params['watched']=='true')
        elif operation=='progress_clear':
            if not xbmcgui.Dialog().yesno('Clear viewing record?', 'Remove this title’s saved position and watched state? Your lists and ratings are kept.'):return
            store.remove(item)
        elif operation in ('progress_save','progress_unsave','progress_lists'):
            from resources.lib.library_ui import title_row,action as library_action
            media='tv' if item['media_type']=='episode' else 'movie'
            if operation=='progress_lists':library_action(addon,core,dict(action='library_manage',media_type=media,tmdb_id=item['tmdb_id']));return
            library=Library(addon)
            if operation=='progress_unsave':library.remove(1,media,item['tmdb_id'])
            else:library.add(title_row(library,addon,core,media,item['tmdb_id']))
        else:raise ProgressError('Unknown viewing action.')
        xbmcgui.Dialog().notification('MDM Flix','Saved on this device.',xbmcgui.NOTIFICATION_INFO,2000);xbmc.executebuiltin('Container.Refresh')
    except (ProgressError,LibraryError,CatalogueError) as error:xbmcgui.Dialog().ok('Viewing progress',str(error))
