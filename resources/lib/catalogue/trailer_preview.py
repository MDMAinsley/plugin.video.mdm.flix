"""Own a single muted Home preview and hand it to the fullscreen player."""
import json
from collections import deque
from queue import Empty, SimpleQueue
from threading import Thread
from time import monotonic
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import xbmc
import xbmcgui

from resources.lib.catalogue import trailers

ENABLED = 'mdm_preview_enabled'
ACTIVE = 'mdm_preview_active'
FULLSCREEN = 'mdm_preview_fullscreen'
DELAY = 5
START_TIMEOUT = 12
# Kodi's cancellable and non-cancellable player busy windows.
PLAYER_BUSY_DIALOGS = (10138, 10160)
NO_MODAL_DIALOG = 9999


def request_fullscreen():
    window = xbmcgui.Window(10000)
    token = window.getProperty(ACTIVE)
    if token:
        window.setProperty(FULLSCREEN, token)


def rpc(method, **params):
    try:
        response = json.loads(xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params,
        })))
        return response.get('result') if isinstance(response, dict) else None
    except (RuntimeError, ValueError, TypeError):
        return None


class HomePreview:
    def __init__(self, addon, core):
        self.addon = addon
        self.core = core
        self.window = xbmcgui.Window(10000)
        self.player = xbmc.Player()
        self.focus = None
        self.focus_since = 0
        self.generation = 0
        self.attempted = False
        self.loading = False
        self.results = SimpleQueue()
        self.token = None
        self.path = None
        self.deadline = 0
        self.cancelled = False
        self.started = False
        self.restore_audio = False
        self.cancelled_paths = deque(maxlen=8)
        self.window.clearProperty(ACTIVE)
        self.window.clearProperty(FULLSCREEN)

    def focused_title(self):
        if (self.core is None or self.window.getProperty(ENABLED) != 'true'
                or self.addon.getSetting('device_home_previews') == 'false'
                or xbmcgui.getCurrentWindowId() != 10000):
            return None
        dialog = xbmcgui.getCurrentWindowDialogId()
        modal = xbmc.getCondVisibility('System.HasActiveModalDialog')
        if self.path and (dialog in PLAYER_BUSY_DIALOGS or (dialog == NO_MODAL_DIALOG and modal)):
            # Kodi evaluates rail labels in the dialog context while resolving
            # video. The modal flag can also change before Kodi exposes its ID.
            # Recheck the actual Home card once that dialog goes away.
            return self.focus
        if modal:
            return None
        try:
            rail = self.window.getFocusId()
        except RuntimeError:
            return None
        if rail not in trailers.HOME_RAILS:
            return None
        path = urlsplit(xbmc.getInfoLabel(f'Container({rail}).ListItem.Property(mdm_home_title)'))
        params = parse_qs(path.query)
        if path.netloc != 'plugin.video.mdm.flix' or params.get('action') != ['home_title']:
            return None
        media = params.get('media_type', [''])[0]
        identifier = params.get('tmdb_id', [''])[0]
        if media in ('movie', 'episode', 'tv') and identifier.isdecimal():
            return rail, path.query, 'movie' if media == 'movie' else 'tv', int(identifier)
        return None

    def load(self, focus):
        self.loading = True
        generation = self.generation
        def lookup():
            video = None
            try:
                if trailers.youtube_state() is True:
                    video = trailers.find(self.addon, self.core, focus[2], focus[3],
                                          lambda: generation != self.generation)
            except (trailers.CatalogueError, RuntimeError):
                pass
            finally:
                self.results.put((generation, video))
        Thread(target=lookup, name='MDM Home trailer lookup', daemon=True).start()

    def start(self, video, now):
        if self.player.isPlaying():
            return
        audio = rpc('Application.GetProperties', properties=['muted'])
        if not isinstance(audio, dict) or type(audio.get('muted')) is not bool:
            return
        if not audio['muted']:
            if rpc('Application.SetMute', mute=True) is not True:
                return
            self.restore_audio = True
        self.token = uuid4().hex
        self.path = trailers.video_url(video['key'], mdm_preview=self.token)
        self.deadline = now + START_TIMEOUT
        try:
            item = xbmcgui.ListItem(label='Trailer preview', path=self.path)
            item.setProperty('mdm.flix.preview', self.token)
            self.player.play(self.path, item, windowed=True)
        except RuntimeError:
            self.release()

    def playing_path(self):
        try:
            item = self.player.getPlayingItem()
            return item.getProperty('original_listitem_url') or item.getPath()
        except RuntimeError:
            return ''

    def owns_playback(self):
        if not self.path or not self.player.isPlayingVideo():
            return False
        try:
            item = self.player.getPlayingItem()
            return (item.getProperty('mdm.flix.preview') == self.token
                    or self.playing_path() == self.path)
        except RuntimeError:
            return False

    def playback_has_started(self):
        try:
            return self.player.isPlaying() and self.player.getTime() > 0
        except RuntimeError:
            return False

    def release(self):
        self.window.clearProperty(ACTIVE)
        self.window.clearProperty(FULLSCREEN)
        self.token = self.path = None
        self.cancelled = self.started = False
        if self.restore_audio:
            self.restore_audio = False
            audio = rpc('Application.GetProperties', properties=['muted'])
            if isinstance(audio, dict) and audio.get('muted') is True:
                rpc('Application.SetMute', mute=False)

    def interrupt(self):
        if not self.path:
            return True
        self.cancelled = True
        self.window.clearProperty(ACTIVE)
        if self.owns_playback():
            xbmc.executebuiltin('PlayerControl(Stop)')
            self.release()
            return False
        if self.started or self.playback_has_started() or monotonic() >= self.deadline:
            self.cancelled_paths.append(self.path)
            self.release()
            return True
        return False

    def tick(self):
        now = monotonic()
        focus = self.focused_title()
        if focus != self.focus:
            self.focus, self.focus_since = focus, now
            self.generation += 1
            self.attempted = False
            self.interrupt()

        if self.path:
            if self.cancelled:
                self.interrupt()
            elif self.owns_playback():
                self.started = self.started or self.playback_has_started()
                if not self.started:
                    if now >= self.deadline:
                        self.interrupt()
                elif xbmc.getCondVisibility(trailers.BUSY):
                    self.window.clearProperty(ACTIVE)
                elif self.window.getProperty(FULLSCREEN) == self.token:
                    xbmc.executebuiltin('Action(FullScreen)', True)
                    self.release()
                else:
                    self.window.setProperty(ACTIVE, self.token)
            elif self.started or self.playback_has_started() or now >= self.deadline:
                self.interrupt()
        elif self.player.isPlayingVideo() and self.playing_path() in self.cancelled_paths:
            xbmc.executebuiltin('PlayerControl(Stop)')

        try:
            generation, video = self.results.get_nowait()
        except Empty:
            pass
        else:
            self.loading = False
            if (generation == self.generation and video and focus and not self.path
                    and not self.player.isPlaying() and not trailers.pending_request(self.window)):
                self.start(video, now)
        if (focus and not self.path and not self.loading and not self.attempted
                and now - self.focus_since >= DELAY and not self.player.isPlaying()
                and not trailers.pending_request(self.window)):
            self.attempted = True
            self.load(focus)

    def close(self):
        self.generation += 1
        try:
            if self.owns_playback():
                xbmc.executebuiltin('PlayerControl(Stop)')
        finally:
            self.release()
