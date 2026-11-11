"""On-demand title trailers, separate from feature playback and tracking."""
import json
import re
import time
from collections import deque
from urllib.parse import urlencode
from uuid import uuid4

import xbmc
import xbmcgui

from resources.lib.catalogue.tmdb import TMDB, CatalogueError, number

YOUTUBE = 'plugin.video.youtube'
VIDEO_KEY = re.compile(r'[A-Za-z0-9_-]{11}')
REQUEST_ID = re.compile(r'[0-9a-f]{32}')
PLAY_REQUEST = 'mdm.flix.trailer.play_request'
BUSY = 'Container.IsUpdating | System.HasActiveModalDialog'
HOME_RAILS = (5300, 5500, 5400, 5100, 5200)


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


def video_url(key, **params):
    return 'plugin://plugin.video.youtube/play/?' + urlencode(dict(video_id=key, incognito='true', **params))


def view_context():
    window_id = xbmcgui.getCurrentWindowId()
    if window_id == 10000:
        for rail in HOME_RAILS:
            if xbmc.getCondVisibility(f'Control.HasFocus({rail})'):
                return [window_id, rail, xbmc.getInfoLabel(f'Container({rail}).ListItem.Property(mdm_home_title)')]
    return [window_id, xbmc.getInfoLabel('Container.FolderPath')]


def pending_request(window):
    try:
        return json.loads(window.getProperty(PLAY_REQUEST))['expires'] > time.monotonic()
    except (ValueError, TypeError, KeyError):
        return False


def show(nav, addon, core, params):
    """Queue playback while keeping the originating Kodi window visible."""
    from resources.lib.playback.progress_ui import title_identity
    from resources.lib.playback.progress import ProgressError

    context = view_context()
    dialog = xbmcgui.Dialog()
    try:
        item = title_identity(params)
        media = 'movie' if item['media_type'] == 'movie' else 'tv'
        monitor = xbmc.Monitor()
        video = find(addon, core, media, item['tmdb_id'], monitor.abortRequested)
        if monitor.abortRequested():
            return
        if video is None:
            dialog.notification('Watch Trailer', 'No official trailer is listed for this title.')
            return
        if not ready() or context != view_context():
            return
    except (CatalogueError, ProgressError):
        dialog.notification('Watch Trailer', 'The trailer listing could not be loaded.')
        return
    xbmcgui.Window(10000).setProperty(PLAY_REQUEST, json.dumps({
        'id': uuid4().hex, 'key': video['key'], 'expires': time.monotonic() + 8,
        'context': context,
    }))


class TrailerPlayback:
    """Start an explicit request after the originating window settles."""

    def __init__(self):
        self.window = xbmcgui.Window(10000)
        self.finished = deque(maxlen=32)
        self.pending = None
        self.settled = False

    def tick(self, preview=None):
        try:
            request = json.loads(self.window.getProperty(PLAY_REQUEST))
            token, key, expires = request['id'], request['key'], request['expires']
            if not REQUEST_ID.fullmatch(token) or not VIDEO_KEY.fullmatch(key):
                return
            if token in self.finished:
                return
            if time.monotonic() >= expires or request['context'] != view_context():
                self.finished.append(token)
                return
            if self.pending != token:
                self.pending, self.settled = token, False
            if xbmc.getCondVisibility(BUSY):
                self.settled = False
                return
            if not self.settled:
                self.settled = True
                return
            if preview is not None and not preview.interrupt():
                return
            self.finished.append(token)
            if xbmc.getCondVisibility('Player.HasMedia'):
                xbmcgui.Dialog().notification('Watch Trailer', 'Stop the current video before playing a trailer.')
                return
            xbmc.executeJSONRPC(json.dumps(dict(jsonrpc='2.0', id=1, method='Player.Open',
                                               params=dict(item=dict(file=video_url(key)), options=dict(resume=False)))))
        except (ValueError, TypeError, KeyError, RuntimeError):
            return
