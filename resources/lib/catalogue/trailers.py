"""On-demand title trailers, separate from feature playback and tracking."""
import json
import re
import time
from collections import deque
from urllib.parse import parse_qs, urlencode, urlsplit

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib.catalogue.tmdb import TMDB, CatalogueError, number
from resources.lib.metadata.listitem import create_playable_item

YOUTUBE = 'plugin.video.youtube'
VIDEO_KEY = re.compile(r'[A-Za-z0-9_-]{11}')
REQUEST_ID = re.compile(r'[0-9a-f]{32}')
PLAY_REQUEST = 'mdm.flix.trailer.play_request'
FLIX = 'plugin.video.mdm.flix'
BUSY = 'Container.IsUpdating | Window.IsActive(progressdialog) | Window.IsActive(busydialog) | Window.IsActive(busydialognocancel)'


def candidates(data, identifier, language):
    if type(data.get('id')) is not int or data['id'] != identifier:
        raise CatalogueError('The trailer listing does not match this title.')
    rows = []
    for row in data['results'][:200]:
        if (isinstance(row, dict) and row.get('site') == 'YouTube'
                and row.get('type') == 'Trailer' and row.get('official') is True
                and isinstance(row.get('key'), str) and VIDEO_KEY.fullmatch(row['key'])
                and row.get('iso_639_1') in (language[:2], 'en', None)):
            rows.append(row)
    # Newest first within each preference. Never use arbitrary returned URLs.
    rows.sort(key=lambda row: str(row.get('published_at', ''))[:32], reverse=True)
    rows.sort(key=lambda row: row.get('iso_639_1') != language[:2])
    return rows


def find(addon, core, media, identifier, cancelled=lambda: False):
    if media not in ('movie', 'tv'):
        raise CatalogueError('Unknown trailer title type.')
    identifier = number(identifier, 1)
    client = TMDB(addon, core)
    languages = list(dict.fromkeys((client.language, 'en-US')))
    for language in languages:
        if cancelled():
            return None
        data = client.request(f'{media}/{identifier}/videos', {'language': language}, field='results', ttl=3600)
        rows = candidates(data, identifier, client.language)
        if cancelled():
            return None
        if rows:
            return rows[0]
    return None


def youtube_state():
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps(dict(
            jsonrpc='2.0', id=1, method='Addons.GetAddonDetails',
            params={'addonid': YOUTUBE, 'properties': ['enabled']}))))
        return response['result']['addon']['enabled']
    except (ValueError, KeyError, TypeError):
        return None


def ready():
    state = youtube_state()
    if state is True:
        return True
    dialog = xbmcgui.Dialog()
    if state is False:
        if not dialog.yesno('Watch Trailer', 'Enable the YouTube add-on to play trailers?',
                            yeslabel='Enable YouTube', nolabel='Later'):
            return False
        xbmc.executeJSONRPC(json.dumps(dict(jsonrpc='2.0', id=1, method='Addons.SetAddonEnabled',
                                            params={'addonid': YOUTUBE, 'enabled': True})))
    else:
        if not dialog.yesno('Watch Trailer', 'Trailers play through Kodi’s YouTube add-on. Install it now?',
                            yeslabel='Install YouTube', nolabel='Later'):
            return False
        xbmc.executebuiltin('InstallAddon(plugin.video.youtube)', True)
    dialog.ok('Watch Trailer', 'Once YouTube is ready, choose Watch Trailer again.')
    return False


def show(nav, addon, core, params):
    """List a native video item after the title dialog and lookup have finished."""
    from resources.lib.playback.progress_ui import title_identity
    from resources.lib.playback.progress import ProgressError

    nav.category('Trailers')
    try:
        item = title_identity(params)
        media = 'movie' if item['media_type'] == 'movie' else 'tv'
        monitor = xbmc.Monitor()
        video = find(addon, core, media, item['tmdb_id'], monitor.abortRequested)
        if monitor.abortRequested():
            return
        if video is None:
            xbmcgui.Dialog().notification('Watch Trailer', 'No official trailer is listed for this title.')
            return
        if youtube_state() is not True:
            nav.add_action('Set up YouTube to play trailers', 'trailer_setup')
            return
        url = 'plugin://plugin.video.youtube/play/?' + urlencode({'video_id': video['key'], 'incognito': 'true'})
        label = 'Play official series trailer' if item['media_type'] == 'episode' else 'Play official trailer'
        xbmcplugin.addDirectoryItem(handle=nav.handle, url=url,
                                    listitem=create_playable_item(label), isFolder=False)
    except (CatalogueError, ProgressError):
        xbmcgui.Dialog().notification('Watch Trailer', 'The trailer listing could not be loaded.')
    finally:
        nav.end('videos', cache=False)

    # Publish only after Kodi has received the regular playable list item.
    request = params.get('trailer_request', '')
    if REQUEST_ID.fullmatch(request):
        xbmcgui.Window(10000).setProperty(PLAY_REQUEST, json.dumps({
            'id': request, 'key': video['key'], 'expires': time.monotonic() + 8,
        }))


class TrailerPlayback:
    """Start an explicit request once the matching Kodi video list is stable."""

    def __init__(self):
        self.window = xbmcgui.Window(10000)
        self.finished = deque(maxlen=32)
        self.visible = None
        self.settled = False

    def tick(self):
        try:
            request = json.loads(self.window.getProperty(PLAY_REQUEST))
            token, key, expires = request['id'], request['key'], request['expires']
            if not REQUEST_ID.fullmatch(token) or not VIDEO_KEY.fullmatch(key):
                return
            if token in self.finished:
                return
            path = urlsplit(xbmc.getInfoLabel('Container.FolderPath'))
            params = parse_qs(path.query)
            matching = (path.scheme == 'plugin' and path.netloc == FLIX
                        and params.get('action') == ['trailer_play']
                        and params.get('trailer_request') == [token]
                        and xbmc.getCondVisibility('Window.IsActive(videos)'))
            if (time.monotonic() >= expires or xbmc.getCondVisibility('Player.HasMedia')
                    or (self.visible == token and not matching)):
                self.finished.append(token)
                return
            if not matching:
                return
            if self.visible != token:
                self.visible, self.settled = token, False
            if xbmc.getCondVisibility(BUSY):
                self.settled = False
                return
            if not self.settled:
                self.settled = True
                return
            self.finished.append(token)
            url = 'plugin://plugin.video.youtube/play/?' + urlencode({'video_id': key, 'incognito': 'true'})
            # The list remains available for a manual retry if Kodi refuses playback.
            xbmc.executeJSONRPC(json.dumps(dict(jsonrpc='2.0', id=1, method='Player.Open',
                                               params=dict(item=dict(file=url), options=dict(resume=False)))))
        except (ValueError, TypeError, KeyError, RuntimeError):
            return
