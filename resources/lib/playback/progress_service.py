"""AV-owned progress observer. No scraping, network, URLs or account operations."""
import threading
import time
import xbmc
import xbmcgui
from resources.lib.playback import tracking
from resources.lib.playback.progress import Store,ProgressError,seconds

class Observer(xbmc.Player):
    def __init__(self,addon):
        super().__init__();self.addon=addon;self.active=None;self.position=0;self.duration=0;self.saved=0;self.warned=False;self.observed=False;self.seek_pending=0;self.seek_deadline=0;self.lock=threading.RLock()

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
            if self.seek_pending:
                if position<max(1,self.seek_pending-10):
                    if time.monotonic()>=self.seek_deadline:
                        self.warning('Resume did not take effect. Your saved position is kept; choose Start again to replace it.')
                        self.active=None
                    return False
                self.seek_pending=0
            self.position=position;self.duration=duration;self.observed=True;return True
        except (RuntimeError,ProgressError):return False

    def write(self,force=False,ended=False):
        if not self.active or not self.observed:return
        if self.addon.getSetting('progress_enabled')=='false':self.active=None;return
        if not force and time.monotonic()-self.saved<15:return
        # A failed player or unknown/very short duration never auto-completes.
        watched=bool(self.duration>=60 and self.position>=self.duration*.9)
        if ended and self.duration>=60 and self.position>=self.duration*.9:watched=True
        try:
            Store(self.addon).save(self.active['item'],self.position,self.duration,watched)
        except ProgressError as error:self.warning(str(error))
        self.saved=time.monotonic()

    def onAVStarted(self):
        with self.lock:
            try:
                if self.addon.getSetting('progress_enabled')=='false' or not self.isPlayingVideo():return
                candidate=tracking.read(self.getPlayingItem())
                if self.active and candidate and candidate['token']==self.active['token']:return
                if self.active:self.write(True)
                self.active=None
                if not candidate:return
                self.active=candidate;self.position=0;self.duration=0;self.saved=0;self.warned=False;self.observed=False;self.seek_pending=0
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
                self.write(True);self.active=None;return
            if self.sample():self.write()

    def onPlayBackPaused(self):
        with self.lock:
            if self.sample():self.write(True)

    def finish(self,ended=False):
        with self.lock:
            if self.active:self.write(True,ended)
            self.active=None

    def onPlayBackStopped(self):self.finish()
    def onPlayBackEnded(self):self.finish(True)
    def onPlayBackError(self):
        # Preserve the last confirmed checkpoint; an error is not completion.
        with self.lock:
            if self.active and self.observed and self.addon.getSetting('progress_enabled')!='false':
                try:Store(self.addon).save(self.active['item'],self.position,self.duration,False)
                except ProgressError as error:self.warning(str(error))
            self.active=None

def run(addon):
    observer=Observer(addon);monitor=xbmc.Monitor()
    from resources.lib.playback.episode_controls import Controls
    controls=Controls(addon)
    try:
        while not monitor.waitForAbort(1):
            observer.tick();controls.tick()
    finally:
        controls.close();observer.finish()
