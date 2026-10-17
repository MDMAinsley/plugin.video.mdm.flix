"""Remote-friendly saved-title/list/rating actions; no provider or playback work."""
from urllib.parse import urlencode
import xbmc
import xbmcgui
from resources.lib.library_store import Library, LibraryError, identity, metadata, list_id
from resources.lib.catalogue.tmdb import TMDB, CatalogueError


def command(action, **params):
    return 'RunPlugin(plugin://plugin.video.mdm.flix/?'+urlencode(dict(params,action=action))+')'


def name_input(default=''):
    keyboard=xbmc.Keyboard(default,'List name (up to 50 characters)')
    keyboard.doModal()
    return keyboard.getText() if keyboard.isConfirmed() else None


def title_row(library, addon, core, media, identifier):
    return library.get(media,identifier) or metadata(TMDB(addon,core).details(media,identifier),media,identifier)


def show(nav, addon, core, params):
    try:
        library=Library(addon)
        if params.get('action')=='library_home':
            nav.add_folder('Continue Watching','continue_watching')
            nav.add_folder('Viewing History / watched status','viewing_history')
            for label,kind in [('All saved and rated titles','all'),('Films in your library','movie'),('TV shows in your library','tv'),('Your rated titles','rated')]:
                nav.add_folder(label,'library_view',params={'filter':kind})
            for row in library.lists():
                context=[]
                if row['id']!=1:
                    context=[('Rename list',command('library_rename',list_id=row['id'])),('Delete list',command('library_delete',list_id=row['id']))]
                nav.add_folder('{} ({})'.format(row['name'],row['count']),'library_view',params={'list_id':row['id']},context_menu=context)
            nav.add_action('Create a list…','library_create')
            nav.end('videos');return
        identifier=params.get('list_id')
        kind=params.get('filter','all')
        rows=library.rows(identifier,kind)
        from resources.lib.catalogue.cards import add_title
        from resources.lib.catalogue.browse import artwork, info
        for row in rows:
            raw=dict(id=row['tmdb_id'],title=row['title'],name=row['title'],release_date=row['date'],first_air_date=row['date'],overview=row['plot'],poster_path=row['poster'],backdrop_path=row['backdrop'])
            details=info(raw,'movie' if row['media']=='movie' else 'tvshow')
            details['plot']+='\n\nYour rating: '+(str(row['personal_rating'])+'/10' if row['personal_rating'] else 'not rated')
            label=row['title']+(' [Film]' if row['media']=='movie' else ' [TV]')
            if row['personal_rating']:
                label+=' · Yours {}/10'.format(row['personal_rating'])
            context=[]
            if identifier is not None:
                for text,action in [('Remove from this list','library_remove'),('Move up','library_up'),('Move down','library_down')]:
                    context.append((text,command(action,list_id=list_id(identifier),media_type=row['media'],tmdb_id=row['tmdb_id'])))
            add_title(nav,addon,label,row['media'],row['tmdb_id'],artwork=artwork(raw,addon=addon),info=details,extra_context=context)
        if not rows:
            nav.add_action('No titles here yet. Use a title’s My Library context menu to save or rate it.','library_help')
        nav.end('videos')
    except (LibraryError,CatalogueError) as error:
        xbmcgui.Dialog().ok('My Library',str(error));nav.end()


def action(addon, core, params):
    changed=False
    try:
        library=Library(addon);operation=params.get('action')
        if operation=='library_help':
            xbmcgui.Dialog().ok('My Library','Hold/menu, keyboard C or right-click a film/show and choose My Library. Lists and your ratings are stored on this device.');return
        if operation=='library_create':
            name=name_input()
            if name is None:return
            library.create(name);changed=True
        elif operation in ('library_rename','library_delete'):
            identifier=list_id(params.get('list_id'))
            row=next((row for row in library.lists() if row['id']==identifier),None)
            if not row:raise LibraryError('That list no longer exists.')
            if operation=='library_rename':
                name=name_input(row['name'])
                if name is None:return
                library.rename(identifier,name);changed=True
            elif xbmcgui.Dialog().yesno('Delete list?', 'Delete “{}”? Titles in other lists and your ratings are kept.'.format(row['name'])):
                library.delete(identifier);changed=True
        else:
            media,identifier=identity(params.get('media_type'),params.get('tmdb_id'))
            if operation in ('library_remove','library_up','library_down'):
                target=list_id(params.get('list_id'))
                if operation=='library_remove':library.remove(target,media,identifier)
                else:library.move(target,media,identifier,-1 if operation=='library_up' else 1)
                changed=True
            elif operation=='library_manage':
                selected=xbmcgui.Dialog().select('My Library', ['Add to a list…','Remove from a list…','Your rating…'])
                if selected==0:
                    lists=library.lists()
                    choice=xbmcgui.Dialog().select('Add to list',[row['name'] for row in lists])
                    if not 0<=choice<len(lists):return
                    row=title_row(library,addon,core,media,identifier)
                    library.add(row,lists[choice]['id']);changed=True
                elif selected==1:
                    lists=library.memberships(media,identifier)
                    if not lists:
                        xbmcgui.Dialog().ok('My Library','This title is not in a saved list.');return
                    choice=xbmcgui.Dialog().select('Remove from list',[row['name'] for row in lists])
                    if not 0<=choice<len(lists):return
                    library.remove(lists[choice]['id'],media,identifier);changed=True
                elif selected==2:
                    choice=xbmcgui.Dialog().select('Your rating (separate from TMDB)', ['Clear your rating']+[str(i)+'/10' for i in range(1,11)])
                    if not 0<=choice<=10:return
                    if choice==0 and library.get(media,identifier) is None:return
                    row=title_row(library,addon,core,media,identifier)
                    library.rate(row,choice);changed=True
            else:raise LibraryError('Unknown library action.')
        if changed:
            xbmcgui.Dialog().notification('My Library','Saved on this device.',xbmcgui.NOTIFICATION_INFO,2000)
            xbmc.executebuiltin('Container.Refresh')
    except (LibraryError,CatalogueError) as error:
        xbmcgui.Dialog().ok('My Library',str(error))
