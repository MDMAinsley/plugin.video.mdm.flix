"""AV-owned progress observer. No scraping, network, URLs or account operations."""
import threading
import time
import uuid
import xbmc
import xbmcgui
from resources.lib.playback import tracking
from resources.lib.playback.progress import Store,ProgressError,seconds
from resources.lib.home_rows import invalidate

CHECKPOINT_INTERVAL = 10

class Observer(xbmc.Player):
    def __init__(self,addon):
        super().__init__();self.addon=addon;self.active=None;self.position=0;self.duration=0;self.saved=0;self.last_written=None;self.warned=False;self.observed=False;self.seek_pending=0;self.seek_deadline=0;self.lock=threading.RLock()
        self.sampled=0
        self.sync_id=None
        self.history_sync=False
        self.boot_id=uuid.uuid4().hex

    def current_token(self):
        try:
            if not self.isPlayingVideo():return None
            import json
            # Active ownership may outlive the five-minute initial-claim window.
            raw=self.getPlayingItem().getProperty(tracking.PROPERTY)
            return json.loads(raw).get('token') if isinstance(raw,str) and len(raw)<=8192 else None
        except Exception:return None

    def warning(self,message):
        if not self.warned:
            self.warned=True;xbmcgui.Dialog().notification('MDM Flix',message)

    def sample(self):
        if not self.active or self.current_token()!=self.active['token']:return False
        try:
            position=seconds(self.getTime());duration=seconds(self.getTotalTime())
            # Player reads are separate calls. Discard a sample taken across a handoff.
            if self.current_token()!=self.active['token']:return False
            if self.seek_pending:
                if position<max(1,self.seek_pending-10):
                    if time.monotonic()>=self.seek_deadline:
                        self.warning('Resume did not take effect. Your saved position is kept; choose Start again to replace it.')
                        self.active=None
                    return False
                self.seek_pending=0
            self.position=position;self.duration=duration;self.sampled=time.time();self.observed=True;return True
        except (RuntimeError,ProgressError):return False

    def write(self,force=False,failed=False,final=False):
        if not self.active or not self.observed:return
        if self.addon.getSetting('progress_enabled')=='false':self.active=None;return
        if not force and time.monotonic()-self.saved<CHECKPOINT_INTERVAL:return
        watched=not failed and self.duration>=60 and self.position>=self.duration*.9
        checkpoint=(self.position,self.duration,watched)
        sync=(self.sync_id,self.sampled,None if final else self.boot_id) if self.sync_id and not failed else None
        action=(self.sync_id,'watched',self.sampled,None) if watched and final and self.history_sync else None
        if checkpoint==self.last_written and not (self.sync_id and (final or failed)):
            if final or failed:
                invalidate('continue')
            return
        try:
            Store(self.addon).save(self.active['item'],*checkpoint,sync=sync,
                                  cancel_sync=self.last_written is None or failed,action=action)
            self.last_written=checkpoint
            if final or failed:
                invalidate('continue')
        except ProgressError as error:self.warning(str(error))
        self.saved=time.monotonic()

    def onAVStarted(self):
        from resources.lib.playback import next_prompt
        next_prompt.clear()
        with self.lock:
            try:
                if self.addon.getSetting('progress_enabled')=='false':
                    self.active=None;return
                candidate=tracking.read(self.getPlayingItem()) if self.isPlayingVideo() else None
                if self.active and candidate and candidate['token']==self.active['token']:return
                if self.active:self.write(True,final=True)
                self.active=None
                if not candidate:return
                self.active=candidate;self.position=0;self.duration=0;self.last_written=None;self.warned=False;self.observed=False;self.seek_pending=0
                from resources.lib.mdblist_account import State, MDBError
                try:
                    account=State(self.addon).connection() or {}
                except MDBError:
                    account={}
                self.sync_id=account.get('sync_id')
                self.history_sync=bool(self.sync_id and account.get('history_sync'))
                resume=candidate['resume']
                if resume:
                    duration=seconds(self.getTotalTime())
                    if duration and resume>=duration-10:
                        self.warning('This video has a different length; starting from the beginning.')
                    else:
                        try:
                            self.seekTime(resume);self.seek_pending=resume;self.seek_deadline=time.monotonic()+15
                        except RuntimeError:
                            self.warning('This video could not resume. Your saved position is kept; choose Start again to replace it.')
                            self.active=None;return
                # Do not replace a good resume point with an unconfirmed zero
                # immediately after an asynchronous seek. First sample on tick.
                self.saved=time.monotonic()
            except (RuntimeError,ProgressError):self.active=None

    def tick(self):
        with self.lock:
            if not self.active:return
            if self.current_token()!=self.active['token']:
                self.write(True,final=True);self.active=None;return
            if self.sample():self.write()

    def onPlayBackPaused(self):
        with self.lock:
            if self.sample():self.write(True)

    def onPlayBackSeek(self,time,seekOffset):
        with self.lock:
            if self.sample():self.write(True)

    def onPlayBackSeekChapter(self,chapter):
        with self.lock:
            if self.sample():self.write(True)

    def finish(self):
        with self.lock:
            # Kodi can clear the player before Stop or Exit reaches Python.
            # The latest owned sample survives when the final read is unavailable.
            if self.active:
                self.sample()
                self.write(True,final=True)
            self.active=None

    def onPlayBackStopped(self):
        from resources.lib.playback import next_prompt
        next_prompt.clear()
        self.finish()
    def onPlayBackEnded(self):
        from resources.lib.playback import next_prompt
        next_prompt.ended()
        self.finish()
    def onPlayBackError(self):
        from resources.lib.playback import next_prompt
        next_prompt.clear()
        # Preserve the last confirmed checkpoint; an error is not completion.
        with self.lock:
            self.write(True,failed=True)
            self.active=None

def run(addon):
    from resources.lib.session import clear_sources
    profile=addon.getAddonInfo('profile')
    clear_sources(profile)
    observer=Observer(addon);monitor=xbmc.Monitor()
    from resources.lib.playback.episode_controls import Controls
    controls=Controls(addon)
    from resources.lib.playback.timing_service import start
    timing_worker=start(addon,monitor)
    from resources.lib.playback.contributions import start as start_sharing
    sharing_worker=start_sharing(addon,monitor)
    from resources.lib.playback.native_identity import start as start_identity
    identity_worker=start_identity(addon,monitor)
    from resources.lib.mdblist_resume import start as start_resume_sync
    resume_worker=start_resume_sync(addon,monitor,observer.boot_id)
    from resources.lib.catalogue.artwork_recovery import start as start_artwork
    artwork_worker=start_artwork(addon,monitor)
    from resources.lib.catalogue.trailers import TrailerPlayback
    from resources.lib.catalogue.trailer_preview import HomePreview
    from resources.lib.bootstrap import _load_core
    trailer_playback = TrailerPlayback()
    preview = HomePreview(addon, _load_core())
    from resources.lib.catalogue.voice_setup import WatchSetting
    voice_setup = WatchSetting(addon)
    next_observation = time.monotonic()
    try:
        while not monitor.waitForAbort(0.25):
            preview.tick()
            now = time.monotonic()
            if now >= next_observation:
                observer.tick();controls.tick()
                trailer_playback.tick(preview)
                voice_setup.tick()
                next_observation = now + 1
    finally:
        try:
            try:
                preview.close()
            finally:
                try:
                    observer.finish()
                finally:
                    controls.close()
        finally:
            clear_sources(profile)
