"""On-demand title trailers, separate from feature playback and tracking."""
import json
import os
import re
from urllib.parse import urlencode

import xbmc
import xbmcgui

from resources.lib.catalogue.tmdb import TMDB, CatalogueError, number

YOUTUBE = 'plugin.video.youtube'
VIDEO_KEY = re.compile(r'[A-Za-z0-9_-]{11}')


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


def play(addon, core, params):
    """Only an explicit action starts a trailer; no MDM playback token is stamped."""
    from resources.lib.playback.progress_ui import title_identity
    from resources.lib.playback.progress import ProgressError

    dialog = xbmcgui.Dialog()
    player = xbmc.Player()
    progress = None
    try:
        item = title_identity(params)
        media = 'movie' if item['media_type'] == 'movie' else 'tv'
        if player.isPlaying():
            dialog.ok('Watch Trailer', 'Stop the current playback before watching a trailer.')
            return False
        progress = xbmcgui.DialogProgress()
        progress.create('Watch Trailer', 'Finding a trailer…')
        video = find(addon, core, media, item['tmdb_id'], progress.iscanceled)
        cancelled = progress.iscanceled()
        progress.close()
        progress = None
        if cancelled:
            return False
        if video is None:
            dialog.ok('Watch Trailer', 'No official YouTube trailer is listed for this title.')
            return False
        if xbmc.getCondVisibility('System.Platform.Windows'):
            # The in-Kodi YouTube handoff can freeze on Windows profiles,
            # including after YouTube setup. Open the same official video externally.
            try:
                os.startfile('https://www.youtube.com/watch?' + urlencode({'v': video['key']}))
            except OSError:
                dialog.ok('Watch Trailer', 'Windows could not open your default browser.')
                return False
            return True
        if not ready() or player.isPlaying():
            return False
        url = 'plugin://plugin.video.youtube/play/?' + urlencode({'video_id': video['key'], 'incognito': 'true'})
        # Use Kodi's normal playback command for external add-ons. In particular,
        # the YouTube resolver can open setup dialogs while resolving the URL.
        xbmc.executebuiltin(f'PlayMedia({url},noresume)')
        return True
    except (CatalogueError, ProgressError):
        dialog.ok('Watch Trailer', 'The trailer listing could not be loaded. Please try again later.')
        return False
    except RuntimeError:
        dialog.ok('Watch Trailer', 'Kodi could not start the trailer. Check that the YouTube add-on is ready.')
        return False
    finally:
        if progress is not None:
            progress.close()
