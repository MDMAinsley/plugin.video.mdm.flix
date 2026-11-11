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


def popup(addon,title,button,valid,closed):
    kind=closed['kind']
    # Defined lazily so the service/policy modules do not allocate GUI windows.
    class Prompt(xbmcgui.WindowXMLDialog):
        def onInit(self):
            if kind!='intro':self.getControl(1).setLabel(title)
            self.getControl(10).setLabel(button)
            self.setFocusId(10)
            if kind=='next':self.getControl(20).setVisible(closed.get('countdown') is not None)
            closed['ready']=True
        def onAction(self,action):
            identifier=action.getId()
            if identifier==13:
                closed['choose'](11,stop=True)
            elif identifier in (12,68,79,229):
                if kind not in ('intro','next','still'):self.close()
                if valid() and xbmc.Player().isPlayingVideo():xbmc.Player().pause()
            elif identifier in (9,10,92,216,247,257):
                closed['choose'](11)
        def onClick(self,identifier):
            if identifier in (10,11) or kind=='still' and identifier==12:
                closed['choose'](identifier,stop=kind=='still' and identifier==11)
    layout={'intro':'MDM_SkipIntro.xml','next':'MDM_NextEpisode.xml','still':'MDM_StillWatching.xml'}
    dialog=Prompt(layout.get(kind,'MDM_EpisodePrompt.xml'),addon.getAddonInfo('path'),'Default','1080i')
    closed['dialog']=dialog
    try:
        if valid():dialog.doModal()
    finally:
        closed['done']=True
        dialog.close()


class Controls:
    def __init__(self,addon,player=None,core=None):
        from resources.lib.playback.player_timings import available
        from resources.lib.playback import next_prompt
        next_prompt.clear()
        next_prompt.clear_chain()
        available(False)
        self.addon=addon;self.player=player or xbmc.Player();self.token=None;self.item=None
        self.core=core;self.next_lookup=None;self.autoplay_count=0;self.unattended=False
        self.shown=set();self.chapters=[];self.chapter_attempts=0;self.chapter_due=0;self.config_due=0
        self.config=None;self.dialog=None;self.closed=False
        self.chapter_key=None;self.marking_due=0;self.feedback_due=None
        self.timing=None;self.external_intro=None;self.external_outro=None;self.observed_duration=0;self.community_intro=[];self.community_outro=[];self.audio_intro=None;self.shared_intro=None;self.shared_outro=None;self.estimated_intro=None;self.audio_hint_signature=None;self.shared_request=None

    def dismiss(self):
        if self.dialog:
            self.dialog['cancelled']=True
            dialog=self.dialog.get('dialog')
            if dialog:
                try:dialog.close()
                except RuntimeError:pass
            self.dialog=None

    def valid(self,token):return not self.closed and self.token==token and current_token(self.player)==token

    def next_valid(self,token):
        from resources.lib.playback import next_prompt
        return self.valid(token) or (not self.closed and self.token==token and self.item
                                    and next_prompt.owns(self.player,token,self.item))

    def prompt(self,kind,title,label,accept,position,duration,window_end=None,runtime_matched=False,online=False,window_start=None,*,target=None,countdown=None):
        from resources.lib.playback import next_prompt
        token=self.token
        next_kind=kind in ('next','still')
        holder={'done':False,'until':None if kind=='intro' or next_kind else time.monotonic()+15,
                'token':token,'kind':kind,'start':window_start,'end':window_end,'online':online,
                'countdown':countdown,'clock':None,'ready':False}
        if next_kind:
            if self.valid(token):next_prompt.offer(token,self.item,target)
            holder['reopen']=lambda:self.prompt(kind,title,label,accept,position,duration,
                window_end,runtime_matched,online,window_start,target=target,countdown=holder['countdown'])
        self.shown.add('next' if next_kind else kind);self.dialog=holder
        def valid():
            if (holder.get('cancelled') or holder['until'] is not None and time.monotonic()>=holder['until']
                    or not (self.next_valid(token) if next_kind else self.valid(token))):return False
            try:
                config=configuration(self.addon,Presets(self.addon).get(self.item['tmdb_id']))
                if not config['enabled'] or not config['intro_enabled' if kind in ('intro','mark_intro','rate_intro') else 'next_enabled']:return False
                if kind in ('intro','mark_intro','rate_intro') and config['intro_mode']=='Off':return False
                if next_kind:
                    if next_prompt.owns(self.player,token,self.item):return True
                at=finite(self.player.getTime());length=finite(self.player.getTotalTime())
                if runtime_matched and kind!='next' and abs(length-duration)>5:return False
                if online and kind!='next' and self.addon.getSetting('episode_timing_lookup')=='false':return False
                if window_end is not None:
                    start=window_start if window_start is not None else position-2
                    return start<=at<window_end and window_end<length-30
                if next_kind:return length>=60 and at<=length and (window_start is None or at>=window_start-1)
                return at>=position-2 and length>=60 and at<=length
            except (EpisodeError,RuntimeError):return False
        def execute():
            if valid():accept(token)
        lock=threading.Lock()
        def choose(choice,*,stop=False):
            with lock:
                if holder.get('choice') is not None or holder.get('cancelled') or holder['done']:
                    return
                eligible=valid()
                holder['choice']=choice
            if next_kind and choice==11:next_prompt.clear()
            dialog=holder.get('dialog')
            if dialog:
                try:dialog.close()
                except RuntimeError:pass
            if not eligible:return
            if stop:
                if self.valid(token):self.player.stop()
            elif next_kind and choice in (10,12,20):
                automatic=countdown is not None or kind=='still'
                count=min(self.autoplay_count+1,next_prompt.CHECK_AFTER) if choice==20 else 0
                self.next(token,automatic=automatic,count=count,unattended=self.unattended or choice==12)
            elif choice==10:
                execute()
        holder['choose']=choose
        threading.Thread(target=popup,args=(self.addon,title,label,valid,holder),name='MDM-EpisodePrompt',daemon=True).start()

    def count_down(self,holder,now,paused=False):
        from resources.lib.playback import next_prompt
        if not holder.get('ready') or holder['countdown'] is None or holder.get('choice') is not None:
            return
        previous=holder['clock']
        holder['clock']=None if paused else now
        if paused:return
        if previous is not None:holder['countdown']-=now-previous
        if holder['countdown']<=0:
            holder['choose'](20)
            return
        try:
            holder['dialog'].getControl(20).setPercent(100*(1-holder['countdown']/next_prompt.COUNTDOWN))
        except (KeyError, RuntimeError):
            pass

    def resolve_next(self,item,lookup):
        from resources.lib.catalogue.tmdb import TMDB,CatalogueError
        from resources.lib.playback.episode_ui import following
        from resources.lib.playback.progress import ProgressError
        from resources.lib.playback.viewing import Viewing
        try:
            try:watched=Viewing(self.addon).watched_keys()
            except ProgressError:watched=()
            lookup['target']=following(TMDB(self.addon,self.core),item['tmdb_id'],item['season'],item['episode'],watched=watched)
        except (CatalogueError,RuntimeError):
            pass
        finally:
            lookup['done']=True

    def skip(self,token,end):
        if not self.valid(token):return
        try:
            self.player.seekTime(end)
            if self.addon.getSetting('episode_feedback_prompt')=='true':
                self.feedback_due=time.monotonic()+3
        except RuntimeError:xbmcgui.Dialog().notification('MDM Flix','This stream could not skip the intro.')

    def mark_intro(self,token):
        if not self.valid(token):return
        from resources.lib.playback.marking import panel
        panel(self.addon, token)

    def next(self,token,*,automatic=False,count=0,unattended=False):
        if not self.next_valid(token):return
        params=dict(action='episode_next',token=token,tmdb_id=self.item['tmdb_id'],season=self.item['season'],episode=self.item['episode'])
        if automatic:params.update(next_autoplay=1,chain_count=count,unattended=int(unattended))
        xbmc.executebuiltin('RunPlugin(plugin://plugin.video.mdm.flix/?'+urlencode(params)+')')

    def tick(self):
        token=current_token(self.player)
        from resources.lib.playback import next_prompt
        if token is None and self.item and next_prompt.owns(self.player,self.token,self.item):
            try:config=configuration(self.addon,Presets(self.addon).get(self.item['tmdb_id']))
            except EpisodeError:
                next_prompt.clear();self.dismiss();return
            if not config['enabled'] or not config['next_enabled']:
                next_prompt.clear()
                self.dismiss()
            elif self.dialog and self.dialog['done']:
                choice=self.dialog.get('choice')
                if choice==11:next_prompt.clear()
                elif choice in (10,12,20):
                    self.dialog=None
                    return
                else:
                    self.dialog['reopen']()
                    return
            else:
                if self.dialog and config['next_autoplay']:
                    self.count_down(self.dialog,time.monotonic())
                return
        if token!=self.token:
            next_prompt.clear()
            from resources.lib.playback.player_timings import available
            available(False)
            self.dismiss();self.token=None;self.item=None;self.shown=set();self.chapters=[];self.chapter_attempts=0;self.chapter_due=0;self.config_due=0
            self.next_lookup=None;self.autoplay_count=0;self.unattended=False
            self.timing=None;self.external_intro=None;self.external_outro=None;self.observed_duration=0;self.community_intro=[];self.community_outro=[];self.audio_intro=None;self.shared_intro=None;self.shared_outro=None;self.estimated_intro=None;self.audio_hint_signature=None;self.shared_request=None;self.marking_due=0;self.feedback_due=None
            if token:
                try:candidate=tracking.read(self.player.getPlayingItem())
                except RuntimeError:candidate=None
                if candidate and candidate['item']['media_type']=='episode':
                    self.token=token;self.item=candidate['item'];self.chapter_key=candidate.get('chapter_key')
                    self.autoplay_count,self.unattended=next_prompt.take(candidate)
                    self.timing=candidate.get('timing')
                    available(True)
        if not self.item or not self.valid(self.token):return
        try:
            position=finite(self.player.getTime());duration=finite(self.player.getTotalTime())
            if not duration or position>duration:return
            now=time.monotonic()
            if now>=self.config_due:
                self.config=configuration(self.addon,Presets(self.addon).get(self.item['tmdb_id']));self.config_due=now+5
                self.external_intro=None;self.external_outro=None;self.community_intro=[];self.community_outro=[];self.audio_intro=None;self.shared_intro=None;self.shared_outro=None;self.estimated_intro=None
                if self.timing:
                    from resources.lib.playback.timing_store import Store,TimingError
                    from resources.lib.playback import timing_service,timing_rules
                    try:
                        store=Store(self.addon)
                        if self.chapter_key and (not self.observed_duration or abs(self.observed_duration-duration)>5):
                            store.observe(self.chapter_key,duration);self.observed_duration=duration
                        timing_service.enqueue(self.addon,self.timing,duration)
                        rows=store.data(self.timing)[0] if timing_service.enabled(self.addon) else []
                        from resources.lib.playback.timing_match import assess
                        pair=assess(rows,duration,mode=timing_rules.policy(self.addon))
                        from resources.lib.playback import audio_timing, shared_timing
                        from resources.lib.playback.intro_consensus import community_candidates
                        digest = audio_timing.file_digest(self.player)
                        audio_key = audio_timing.confirmation_key(digest, self.item)
                        if digest != self.shared_request:
                            shared_timing.request_match(self.addon, digest, self.item)
                            self.shared_request = digest
                        shared = shared_timing.matched_timings(self.addon, digest, self.item, duration, token=self.token)
                        self.shared_intro = shared.get("intro")
                        self.shared_outro = shared.get("outro")
                        self.audio_hint_signature = audio_timing.write_search_hint(
                            self.addon, digest, self.item, duration, rows, self.audio_hint_signature)
                        self.audio_intro = audio_timing.suggestion(self.addon, digest, self.item, duration)
                        self.community_intro = community_candidates(rows, duration, timing_rules.policy(self.addon))
                        self.community_outro = community_candidates(rows, duration, timing_rules.policy(self.addon), 'outro')
                        if timing_rules.policy(self.addon) == 'Best available':
                            self.estimated_intro = timing_rules.choose(rows, duration, 'intro')[0]
                        for kind in ('intro','outro'):
                            matched=store.confirmed(self.chapter_key,duration,kind) if self.chapter_key else None
                            if matched is None and kind == 'intro' and audio_key:
                                matched = store.confirmed(audio_key, duration, kind)
                            if matched is None and kind == 'outro':matched=shared.get(kind) or pair.get(kind)
                            if kind=='intro':self.external_intro=matched
                            else:self.external_outro=matched
                    except TimingError:pass
            config=self.config
            if not config['enabled']:
                self.dismiss();return
            if self.core and config['next_enabled'] and self.next_lookup is None:
                self.next_lookup={'done':False,'target':None}
                threading.Thread(target=self.resolve_next,args=(self.item,self.next_lookup),
                                 name='MDM-NextEpisode',daemon=True).start()
            if self.dialog:
                if self.dialog['done']:
                    if self.dialog.get('kind') in ('next','still') and self.dialog.get('choice') is None:
                        self.dialog['reopen']()
                        return
                    self.dialog=None
                else:
                    holder=self.dialog
                    expired=holder['until'] is not None and now>=holder['until']
                    outside=(holder['end'] is not None and position>=holder['end']
                             or holder.get('start') is not None and position<holder['start'])
                    active=config['intro_enabled'] if holder.get('kind') in ('intro','mark_intro','rate_intro') else config['next_enabled']
                    if holder.get('kind') in ('intro','mark_intro','rate_intro') and config['intro_mode']=='Off':active=False
                    if holder.get('online') and holder.get('kind')=='intro' and self.addon.getSetting('episode_timing_lookup')=='false':active=False
                    if expired or outside or not active:
                        if outside and holder.get('kind')=='intro':self.shown.discard('intro')
                        if holder['kind'] in ('next','still'):
                            next_prompt.clear()
                            self.shown.discard('next')
                        self.dismiss()
                    else:
                        if holder['kind']=='next' and config['next_autoplay']:
                            self.count_down(holder,now,xbmc.getCondVisibility('Player.Paused'))
                        return
            if xbmc.getCondVisibility('Player.Paused') or not xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):return
            if self.feedback_due is not None and now>=self.feedback_due:
                self.feedback_due=None
                if self.addon.getSetting('episode_feedback_prompt')=='true':
                    def rate_intro(token):
                        from resources.lib.playback.timing_feedback import panel
                        panel(self.addon,token,'intro')
                    self.prompt('rate_intro','Was the intro timing right?','Rate intro timing',
                                rate_intro,position,duration);return
            # Probe only three times after AV start. Old Kodi may lack the method.
            if self.chapter_attempts<3 and now>=self.chapter_due and (config['prefer_chapters'] or config['intro_mode']=='Chapters' or config['next_mode']=='Chapters'):
                self.chapters=chapter_marks(read_chapters(),duration);self.chapter_attempts+=1;self.chapter_due=now+10
                from resources.lib.playback.media_metadata import chapters
                from resources.lib.playback.episode_policy import INTRO,CREDITS
                cached=chapter_marks(chapters(self.addon,self.chapter_key,duration),duration)
                if cached and not any(name in INTRO|CREDITS for _,name in self.chapters):self.chapters=cached
                if self.chapters:
                    self.chapter_attempts=3
                    if self.valid(self.token) and self.chapter_key:
                        from resources.lib.playback.chapter_facts import Facts
                        Facts(self.addon).remember(self.chapter_key,True)
            from resources.lib.playback.intro_consensus import choose
            from resources.lib.playback.episode_policy import chapter_intro
            chapter = chapter_intro(self.chapters, duration) if config['prefer_chapters'] or config['intro_mode']=='Chapters' else None
            timing = choose(duration, chapter, self.external_intro, self.community_intro,
                            self.audio_intro, self.shared_intro)
            if timing is None and self.estimated_intro:
                timing = dict(self.estimated_intro, unverified=True, online=True)
            external = timing['range'] if timing else None
            intro = intro_range(config, [] if chapter else self.chapters, duration, external)
            from resources.lib.playback.timing_ui import playing
            from resources.lib.playback import timing_feedback
            context=playing() if self.timing else None
            if context and context['token']==self.token and intro:
                observation=dict(timing or {},kind='intro',start=intro[0],end=intro[1])
                timing_feedback.remember(context,observation,'intro')
            if intro and 'intro' not in self.shown and intro[0]<=position<intro[1]-2:
                matched = bool(timing and intro == external)
                self.prompt('intro','','Skip Intro',
                            lambda token:self.skip(token,intro[1]),position,duration,intro[1],matched,
                            matched and timing['online'],window_start=intro[0]);return
            from resources.lib.playback.marking import draft
            from resources.lib.playback.timing_ui import playing
            context = playing() if self.timing else None
            active_draft = draft(context) if context and context['token']==self.token else None
            if active_draft and now>=self.marking_due:
                self.marking_due=now+30
                kind=active_draft['kind']
                def continue_marking(token, kind=kind):
                    from resources.lib.playback.marking import panel
                    panel(self.addon, token, kind)
                self.prompt('mark_'+kind,'Mark '+kind+' · draft saved','Continue marking',
                            continue_marking,position,duration);return
            if (not active_draft and not intro and 'mark_intro' not in self.shown and self.timing
                    and config['intro_enabled'] and config['intro_mode']!='Off'
                    and 30<=position<=min(240,duration*.4)):
                self.prompt('mark_intro','No intro timing found','Mark intro',
                            self.mark_intro,position,duration);return
            from resources.lib.playback.episode_policy import CREDITS
            chapter_end = None
            if config['prefer_chapters'] or config['next_mode']=='Chapters':
                chapter_end = next(((at,duration) for at,name in self.chapters
                                    if name in CREDITS and duration*.5<=at<=duration-3), None)
            confirmed_end = self.external_outro if (self.external_outro and
                self.external_outro.get('provider')=='Your confirmed timing') else None
            ending = choose(duration, chapter_end, confirmed_end, self.community_outro,
                            shared=self.shared_outro, kind='outro')
            self.external_outro = ending or self.external_outro
            if context and context['token']==self.token and self.external_outro:
                bounds=self.external_outro['range']
                timing_feedback.remember(context,dict(self.external_outro,kind='outro',
                    start=bounds[0],end=bounds[1]),'outro')
            trusted_outro = ending and ending.get('tier')=='trusted reviewer'
            external_end=self.external_outro['range'][0] if self.external_outro else None
            trigger=next_at(config,[] if trusted_outro else self.chapters,duration,external_end)
            if trigger is not None and config['next_autoplay'] and self.core:
                trigger=min(duration-2,max(trigger,duration*.9))
            if trigger is not None and 'next' not in self.shown and trigger<=position<duration-1:
                target=self.next_lookup['target'] if self.next_lookup else None
                if self.core and not target:return
                automatic=config['next_autoplay'] and target is not None
                if automatic and self.autoplay_count>=next_prompt.CHECK_AFTER and not self.unattended:
                    show=self.item.get('tvshowtitle')
                    title=f'Are you still watching “{show}”?' if show else 'Are you still watching?'
                    self.prompt('still',title,'Ask again later',self.next,position,duration,
                                window_start=trigger,target=target)
                else:
                    title='S{season:02d}  E{episode:02d}'.format(**target) if target else ''
                    self.prompt('next',title,'Next Episode',self.next,position,duration,
                                window_start=trigger if automatic else None,target=target,
                                countdown=next_prompt.COUNTDOWN if automatic else None)
        except (EpisodeError,RuntimeError):
            # Episode assistance must never stop playback or the progress observer.
            self.dismiss()

    def close(self):
        from resources.lib.playback.player_timings import available
        from resources.lib.playback import next_prompt
        next_prompt.clear()
        next_prompt.clear_chain()
        available(False)
        self.closed=True;self.dismiss()
