"""Per-show intro setup and deliberate next-episode navigation."""
import json
import re
from datetime import date
from urllib.parse import urlencode
import xbmc
import xbmcgui
from resources.lib.playback.episode_policy import Presets,EpisodeError,timing,configuration
from resources.lib.catalogue.tmdb import TMDB,CatalogueError,number


def settings(nav,addon):
    try:
        nav.add_action('Next episode / Skip intro settings','open_settings')
        for row in Presets(addon).rows():
            nav.add_action(row['title']+(' · On' if row['enabled'] else ' · Off'),'episode_show',params={'tmdb_id':row['id']})
        nav.add_action('How show presets work','episode_help')
        nav.end('videos')
    except EpisodeError as error:xbmcgui.Dialog().ok('Episode controls',str(error));nav.end()


def setup(addon,core,params):
    try:
        if params.get('action')=='episode_help':
            xbmcgui.Dialog().ok('Episode controls','Hold/menu on a show or episode and choose Episode controls. Save an intro start/end once for that show. All its episodes use that preset; chapters take priority in Chapters mode. Disable the show if its timing changes. The new-shows toggle controls shows without a saved preset. Next episode never starts unless you press the button.');return
        identifier=Presets.identifier(params.get('tmdb_id'));store=Presets(addon);row=store.get(identifier)
        title=row['title'] if row else str(TMDB(addon,core).details('tv',identifier).get('name') or 'TV show')[:200]
        row=row or dict(enabled=configuration(addon)['enabled'],intro_mode='Chapters',start=0,end=0)
        selection=xbmcgui.Dialog().select(title+' · Episode controls',[
            'Turn prompts off for this show' if row['enabled'] else 'Turn prompts on for this show',
            'Use chapters (saved range as fallback)', 'Set / replace saved intro range…',
            'Use saved range for every episode', 'Turn Skip Intro off for this show',
            'Remove preset / follow new-show setting'])
        if selection<0:return
        active=row['enabled'];mode=row['intro_mode'];start=row['start'];end=row['end']
        if selection==0:active=not active
        elif selection==1:mode='Chapters';active=True
        elif selection==2:
            def ask(label,default):
                value=xbmcgui.Dialog().input(label,defaultt=str(int(default)),type=xbmcgui.INPUT_ALPHANUM)
                return None if value=='' else timing(value)
            start=ask('Intro starts: seconds or M:SS',start)
            if start is None:return
            end=ask('Intro ends: seconds or M:SS',end)
            if end is None:return
            mode='Custom';active=True
        elif selection==3:mode='Custom';active=True
        elif selection==4:mode='Off'
        elif selection==5:
            if xbmcgui.Dialog().yesno('Remove show preset?', 'This show will follow the new-shows toggle again.'):
                store.remove(identifier);xbmc.executebuiltin('Container.Refresh')
            return
        else:return
        store.save(identifier,title,active,mode,start,end)
        xbmcgui.Dialog().notification('Episode controls','Show preset saved.',xbmcgui.NOTIFICATION_INFO,3000)
        xbmc.executebuiltin('Container.Refresh')
    except (EpisodeError,CatalogueError) as error:xbmcgui.Dialog().ok('Episode controls',str(error))


def following(client,identifier,season,episode,today=None):
    """TMDB episode order, including season rollover; no unannounced specials."""
    today=today or date.today().isoformat()
    def candidates(data,season,after):
        result=[]
        for row in data['episodes']:
            if not isinstance(row,dict):continue
            try:at=number(row.get('episode_number'),1)
            except CatalogueError:continue
            if at>after:result.append((at,row))
        if not result:return None
        at,row=min(result,key=lambda value:value[0])
        released=row.get('air_date')
        if not isinstance(released,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',released) or released>today:return False
        return dict(media_type='episode',tmdb_id=identifier,season=season,episode=at)
    result=candidates(client.season(identifier,season),season,episode)
    if result is not None:return result or None
    if season==0:return None
    details=client.details('tv',identifier)
    rows=details.get('seasons')
    if not isinstance(rows,list):raise CatalogueError('TMDB did not return the next season.')
    later=[]
    for row in rows:
        try:at=number(row.get('season_number'),1)
        except (CatalogueError,AttributeError):continue
        if at>season:later.append(at)
    # Only the immediate next listed season: never skip an unaired season.
    if not later:return None
    next_season=min(later)
    return candidates(client.season(identifier,next_season),next_season,0) or None


def play_next(addon,core,params):
    from resources.lib.playback.episode_controls import current_token
    from resources.lib.playback.tracking import PROPERTY
    from resources.lib.playback.progress import clean,ProgressError
    try:
        token=params.get('token','')
        if not re.fullmatch('[0-9a-f]{32}',token):raise EpisodeError('This next-episode prompt has expired.')
        player=xbmc.Player()
        def owned():
            if current_token(player)!=token:return False
            raw=player.getPlayingItem().getProperty(PROPERTY)
            item=clean(json.loads(raw).get('item'))
            return item['media_type']=='episode' and all(str(item[k])==str(params.get(k)) for k in ('tmdb_id','season','episode'))
        if not owned():return
        identifier=number(params.get('tmdb_id'),1);season=number(params.get('season'));episode=number(params.get('episode'),1)
        next_item=following(TMDB(addon,core),identifier,season,episode)
        if not owned():return
        if not next_item:
            xbmcgui.Dialog().notification('MDM Flix','No next aired episode is available yet.',xbmcgui.NOTIFICATION_INFO,4000);return
        action='autoplay' if addon.getSetting('playback_mode')=='Autoplay' else 'sources'
        url='plugin://plugin.video.mdm.flix/?'+urlencode(dict(next_item,action=action))
        player.stop()
        if action=='autoplay':xbmc.executebuiltin('PlayMedia('+url+')')
        else:xbmc.executebuiltin('ActivateWindow(Videos,'+url+',return)')
    except (EpisodeError,CatalogueError,ProgressError,RuntimeError,ValueError,TypeError) as error:
        text=str(error) if isinstance(error,(EpisodeError,CatalogueError)) else 'The next episode could not be opened. Your current progress is kept.'
        xbmcgui.Dialog().ok('Next episode',text)
