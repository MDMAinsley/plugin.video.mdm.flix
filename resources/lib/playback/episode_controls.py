"""Small remote-friendly episode prompts; confirmed MDM playback ownership only."""
import json
import threading
import time
from urllib.parse import urlencode
import xbmc
import xbmcgui
from resources.lib.playback import tracking
from resources.lib.playback.episode_policy import (Presets,EpisodeError,configuration,chapter_marks,intro_range,next_at,finite)


def current_token(player):
    try:
        if not player.isPlayingVideo():return None
        raw=player.getPlayingItem().getProperty(tracking.PROPERTY)
        if not isinstance(raw,str) or len(raw)>8192:return None
        return json.loads(raw).get('token')
    except (ValueError,RuntimeError,AttributeError):return None


def read_chapters():
    try:
        value=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,'method':'Player.GetChapters','params':{'playerid':1}})))
        if 'error' in value:return []
        return value.get('result',{}).get('chapters',[])
    except (ValueError,RuntimeError,AttributeError):return []


def popup(addon,title,button,valid,accept,closed):
    # Defined lazily so the service/policy modules do not allocate GUI windows.
    class Prompt(xbmcgui.WindowXMLDialog):
        def onInit(self):
            self.getControl(1).setLabel(title)
            self.getControl(10).setLabel(button)
            self.setFocusId(10)
        def onAction(self,action):
            identifier=action.getId()
            if identifier==13:
                self.close()
                if valid():xbmc.Player().stop()
            elif identifier in (12,68,79,229):
                self.close()
                if valid():xbmc.Player().pause()
            elif identifier in (9,10,92,216,247,257):self.close()
        def onClick(self,identifier):
            self.close()
            if identifier==10 and valid():accept()
    dialog=Prompt('MDM_EpisodePrompt.xml',addon.getAddonInfo('path'),'Default','1080i')
    closed['dialog']=dialog
    try:
        if valid():dialog.doModal()
    finally:
        closed['done']=True
        dialog.close()


class Controls:
    def __init__(self,addon,player=None):
        self.addon=addon;self.player=player or xbmc.Player();self.token=None;self.item=None
        self.shown=set();self.chapters=[];self.chapter_attempts=0;self.chapter_due=0;self.config_due=0
        self.config=None;self.dialog=None;self.closed=False

    def dismiss(self):
        if self.dialog:
            self.dialog['cancelled']=True
            dialog=self.dialog.get('dialog')
            if dialog:
                try:dialog.close()
                except RuntimeError:pass
            self.dialog=None

    def valid(self,token):return not self.closed and self.token==token and current_token(self.player)==token

    def prompt(self,kind,title,label,accept,position,duration,window_end=None):
        token=self.token;holder={'done':False,'until':time.monotonic()+15,'token':token,'end':window_end}
        self.shown.add(kind);self.dialog=holder
        def valid():
            if holder.get('cancelled') or time.monotonic()>=holder['until'] or not self.valid(token):return False
            try:
                config=configuration(self.addon,Presets(self.addon).get(self.item['tmdb_id']))
                if not config['enabled'] or not config['intro_enabled' if kind=='intro' else 'next_enabled']:return False
                at=finite(self.player.getTime());length=finite(self.player.getTotalTime())
                if window_end is not None:return position-2<=at<window_end and window_end<length-30
                return at>=position-2 and length>=60 and at<=length
            except (EpisodeError,RuntimeError):return False
        def execute():
            if valid():accept(token)
        threading.Thread(target=popup,args=(self.addon,title,label,valid,execute,holder),name='MDM-EpisodePrompt',daemon=True).start()

    def skip(self,token,end):
        if not self.valid(token):return
        try:self.player.seekTime(end)
        except RuntimeError:xbmcgui.Dialog().notification('MDM Flix','This stream could not skip the intro.')

    def next(self,token):
        if not self.valid(token):return
        params=dict(action='episode_next',token=token,tmdb_id=self.item['tmdb_id'],season=self.item['season'],episode=self.item['episode'])
        xbmc.executebuiltin('RunPlugin(plugin://plugin.video.mdm.flix/?'+urlencode(params)+')')

    def tick(self):
        token=current_token(self.player)
        if token!=self.token:
            self.dismiss();self.token=None;self.item=None;self.shown=set();self.chapters=[];self.chapter_attempts=0;self.chapter_due=0;self.config_due=0
            if token:
                try:candidate=tracking.read(self.player.getPlayingItem())
                except RuntimeError:candidate=None
                if candidate and candidate['item']['media_type']=='episode':self.token=token;self.item=candidate['item']
        if not self.item or not self.valid(self.token):return
        try:
            position=finite(self.player.getTime());duration=finite(self.player.getTotalTime())
            if not duration or position>duration:return
            now=time.monotonic()
            if now>=self.config_due:
                self.config=configuration(self.addon,Presets(self.addon).get(self.item['tmdb_id']));self.config_due=now+5
            config=self.config
            if not config['enabled']:
                self.dismiss();return
            if self.dialog:
                if self.dialog['done']:self.dialog=None
                elif now>=self.dialog['until'] or self.dialog['end'] is not None and position>=self.dialog['end'] or xbmc.getCondVisibility('Player.Paused'):
                    self.dismiss()
                else:return
            if xbmc.getCondVisibility('Player.Paused') or not xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):return
            # Probe only three times after AV start. Old Kodi may lack the method.
            if self.chapter_attempts<3 and now>=self.chapter_due and (config['intro_mode']=='Chapters' or config['next_mode']=='Chapters'):
                self.chapters=chapter_marks(read_chapters(),duration);self.chapter_attempts+=1;self.chapter_due=now+10
                if self.chapters:self.chapter_attempts=3
            intro=intro_range(config,self.chapters,duration)
            if intro and 'intro' not in self.shown and intro[0]<=position<intro[1]-2:
                self.prompt('intro','Opening titles','Skip intro',lambda token:self.skip(token,intro[1]),position,duration,intro[1]);return
            trigger=next_at(config,self.chapters,duration)
            if trigger is not None and 'next' not in self.shown and trigger<=position<duration-1:
                self.prompt('next','Ready for the next episode?','Next episode',self.next,position,duration)
        except (EpisodeError,RuntimeError):
            # Episode assistance must never stop playback or the progress observer.
            self.dismiss()

    def close(self):self.closed=True;self.dismiss()
