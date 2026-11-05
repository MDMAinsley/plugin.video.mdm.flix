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
    from resources.lib.playback import next_prompt
    # Defined lazily so the service/policy modules do not allocate GUI windows.
    class Prompt(xbmcgui.WindowXMLDialog):
        def onInit(self):
            self.getControl(1).setLabel(title)
            self.getControl(10).setLabel(button)
            self.setFocusId(10)
        def onAction(self,action):
            identifier=action.getId()
            if identifier==13:
                closed['choice']=11
                if closed.get('kind')=='next':next_prompt.clear()
                self.close()
                if valid():xbmc.Player().stop()
            elif identifier in (12,68,79,229):
                if closed.get('kind') not in ('intro','next'):self.close()
                if valid() and xbmc.Player().isPlayingVideo():xbmc.Player().pause()
            elif identifier in (9,10,92,216,247,257):
                closed['choice']=11
                if closed.get('kind')=='next':next_prompt.clear()
                self.close()
        def onClick(self,identifier):
            closed['choice']=identifier
            if closed.get('kind')=='next' and identifier!=10:next_prompt.clear()
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
        from resources.lib.playback.player_timings import available
        from resources.lib.playback import next_prompt
        next_prompt.clear()
        available(False)
        self.addon=addon;self.player=player or xbmc.Player();self.token=None;self.item=None
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

    def prompt(self,kind,title,label,accept,position,duration,window_end=None,runtime_matched=False,online=False,window_start=None):
        token=self.token
        holder={'done':False,'until':None if kind in ('intro','next') else time.monotonic()+15,
                'token':token,'kind':kind,'start':window_start,'end':window_end,'online':online}
        if kind=='next':
            from resources.lib.playback import next_prompt
            if self.valid(token):next_prompt.offer(token,self.item)
            holder['reopen']=lambda:self.prompt(kind,title,label,accept,position,duration,
                window_end,runtime_matched,online,window_start)
        self.shown.add(kind);self.dialog=holder
        def valid():
            if (holder.get('cancelled') or holder['until'] is not None and time.monotonic()>=holder['until']
                    or not (self.next_valid(token) if kind=='next' else self.valid(token))):return False
            try:
                config=configuration(self.addon,Presets(self.addon).get(self.item['tmdb_id']))
                if not config['enabled'] or not config['intro_enabled' if kind in ('intro','mark_intro','rate_intro') else 'next_enabled']:return False
                if kind in ('intro','mark_intro','rate_intro') and config['intro_mode']=='Off':return False
                if kind=='next':
                    from resources.lib.playback import next_prompt
                    if next_prompt.owns(self.player,token,self.item):return True
                at=finite(self.player.getTime());length=finite(self.player.getTotalTime())
                if runtime_matched and kind!='next' and abs(length-duration)>5:return False
                if online and kind!='next' and self.addon.getSetting('episode_timing_lookup')=='false':return False
                if window_end is not None:
                    start=window_start if window_start is not None else position-2
                    return start<=at<window_end and window_end<length-30
                if kind=='next':return length>=60 and at<=length
                return at>=position-2 and length>=60 and at<=length
            except (EpisodeError,RuntimeError):return False
        def execute():
            if valid():accept(token)
        threading.Thread(target=popup,args=(self.addon,title,label,valid,execute,holder),name='MDM-EpisodePrompt',daemon=True).start()

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

    def next(self,token):
        if not self.next_valid(token):return
        params=dict(action='episode_next',token=token,tmdb_id=self.item['tmdb_id'],season=self.item['season'],episode=self.item['episode'])
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
                elif choice==10:
                    self.dialog=None
                    return
                else:
                    self.dialog['reopen']()
                    return
            else:
                return
        if token!=self.token:
            next_prompt.clear()
            from resources.lib.playback.player_timings import available
            available(False)
            self.dismiss();self.token=None;self.item=None;self.shown=set();self.chapters=[];self.chapter_attempts=0;self.chapter_due=0;self.config_due=0
            self.timing=None;self.external_intro=None;self.external_outro=None;self.observed_duration=0;self.community_intro=[];self.community_outro=[];self.audio_intro=None;self.shared_intro=None;self.shared_outro=None;self.estimated_intro=None;self.audio_hint_signature=None;self.shared_request=None;self.marking_due=0;self.feedback_due=None
            if token:
                try:candidate=tracking.read(self.player.getPlayingItem())
                except RuntimeError:candidate=None
                if candidate and candidate['item']['media_type']=='episode':
                    self.token=token;self.item=candidate['item'];self.chapter_key=candidate.get('chapter_key')
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
            if self.dialog:
                if self.dialog['done']:
                    if self.dialog.get('kind')=='next' and self.dialog.get('choice') is None:
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
                        self.dismiss()
                    else:return
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
                source = timing['provider'] if matched else 'Saved show timing'
                estimated = matched and timing['unverified']
                if estimated:
                    source += ' · unverified'
                self.prompt('intro','Opening titles · '+source,'Estimated skip intro' if estimated else 'Skip intro',
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
            if trigger is not None and 'next' not in self.shown and trigger<=position<duration-1:
                matched=external_end is not None and trigger==external_end
                title='Next episode · '+self.external_outro['provider'] if matched else 'Ready for the next episode?'
                if matched and self.external_outro.get('unverified'):title+=' · unverified'
                self.prompt('next',title,'Play now',self.next,position,duration,runtime_matched=matched,online=matched and self.external_outro.get('online',self.external_outro['provider']!='Your confirmed timing'))
        except (EpisodeError,RuntimeError):
            # Episode assistance must never stop playback or the progress observer.
            self.dismiss()

    def close(self):
        from resources.lib.playback.player_timings import available
        from resources.lib.playback import next_prompt
        next_prompt.clear()
        available(False)
        self.closed=True;self.dismiss()
