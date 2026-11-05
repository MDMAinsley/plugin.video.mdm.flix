"""Background exact-copy identification. No decoder or playback manipulation."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.playback import shared_catalogue,range_identity
from resources.lib.playback.cut_evidence import normalize,groups,RANGES
from resources.lib.playback.timing_store import TimingError

RESET='MDM.Flix.RecheckCut'


def owned():
    try:
        if xbmc.getCondVisibility('Player.Caching'):
            return None
        player=xbmc.Player()
        if player.isExternalPlayer():
            return None
        from resources.lib.playback.timing_ui import playing
        context=playing()
        if not context:
            return None
        address=player.getPlayingFile()
        if not address or hashlib.sha256(address.encode()).hexdigest()!=context['audio_file']:
            return None
        return dict(context,address=address)
    except (RuntimeError,AttributeError,ValueError,TypeError):
        return None


def write(addon,name,value):
    folder=Path(xbmcvfs.translatePath(addon.getAddonInfo('profile')))
    folder.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=folder,delete=False) as stream:
            temporary=Path(stream.name)
            json.dump(value,stream,allow_nan=False)
        os.replace(temporary,folder/name)
        temporary=None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def covered(addon,context):
    data=shared_catalogue.cached(addon)
    if not data or data['schema']!=3:
        return False
    episode=[context['item'][k] for k in ('tmdb_id','season','episode')]
    return any(row['episode']==episode and abs(row['duration']-context['duration'])<=3
               and any(group[0][0]==RANGES for group in groups(row['identities'])) for row in data['cuts'].values())


def identity_key(context):
    return (context['token'],context['audio_file'],*(context['item'][k] for k in ('tmdb_id','season','episode')))


def read_file(context,seconds,cancel):
    address=context['address']
    if range_identity.address(address):
        return range_identity.fingerprint_http(address,seconds=seconds,cancel=cancel)
    if os.path.isabs(address) and not address.startswith(('\\\\','//')):
        return range_identity.fingerprint_file(address,seconds=seconds,cancel=cancel)
    raise range_identity.IdentityError('unsupported_selected_file')


class Worker:
    def __init__(self,addon,current=owned,transport=read_file,abort=lambda:False):
        self.addon=addon
        self.current=current
        self.transport=transport
        self.abort=abort
        self.first={}
        self.attempts={}
        self.reset=''
        self.manual=False
        self.ready={}
        self.status_due=0

    def same(self,context):
        if self.abort() or self.addon.getSetting('episode_native_identity')=='false' or not shared_catalogue.enabled(self.addon):
            return False
        now=self.current()
        return bool(now and identity_key(now)==identity_key(context) and abs(now['duration']-context['duration'])<=2)

    def status(self,status,metrics=None):
        safe={key:metrics[key] for key in ('method','bytes','requests','seconds','consistency') if metrics and key in metrics}
        write(self.addon,'native_cut_status.json',dict(schema=1,status=status,metrics=safe,updated=int(time.time())))

    def tick(self):
        if self.abort() or self.addon.getSetting('episode_native_identity')=='false' or not shared_catalogue.enabled(self.addon):
            return
        try:
            value=xbmcgui.Window(10000).getProperty(RESET)
            if isinstance(value,str) and value and value!=self.reset:
                self.reset=value
                self.manual=True
                self.attempts.clear()
                self.first.clear()
                self.ready.clear()
                xbmcgui.Window(10000).clearProperty(RESET)
        except (RuntimeError,AttributeError):
            pass
        context=self.current()
        if not context:
            return
        key=identity_key(context)
        now=time.monotonic()
        if key not in self.first:
            if len(self.first)>=16:
                self.first.clear()
                self.attempts.clear()
                self.ready.clear()
            self.first[key]=now
            return
        if now-self.first[key]<3:
            return
        previous=self.attempts.get(key)
        if previous and previous[0]>=2:
            if key in self.ready and now>=self.status_due:
                anchors,metrics,was_matched=self.ready[key]
                matched=bool(shared_catalogue.match(self.addon,context['item'],context['duration'],[list(a) for a in anchors]))
                if matched!=was_matched:
                    self.status('Known copy matched' if matched else 'File fingerprint ready; no approved match',metrics)
                    self.ready[key]=(anchors,metrics,matched)
                self.status_due=now+5
            return
        if previous and now<previous[1]:
            return
        from resources.lib.playback.contributions import enabled as sharing
        if not covered(self.addon,context) and not sharing(self.addon) and not self.manual:
            return
        self.manual=False
        self.attempts[key]=((previous[0] if previous else 0)+1,now+60)
        # Invalidate earlier same-session evidence while explicitly rechecking it.
        write(self.addon,'native_cut_evidence.json',dict(schema=1,token=context['token'],file_id=context['audio_file'],status='checking'))
        try:
            low=self.addon.getSetting('device_artwork')=='Light'
            seconds=6 if low else 8
            anchors,metrics=self.transport(context,seconds,lambda:not self.same(context))
            anchors=normalize(anchors)
            if anchors[0][0]!=RANGES or not self.same(context):
                raise range_identity.IdentityError('playback_changed_or_buffering')
            evidence=dict(schema=1,token=context['token'],file_id=context['audio_file'],duration=context['duration'],
                          anchors=anchors,**{k:context['item'][k] for k in ('tmdb_id','season','episode')})
            write(self.addon,'native_cut_evidence.json',evidence)
            matched=shared_catalogue.match(self.addon,context['item'],context['duration'],[list(a) for a in anchors])
            self.status('Known copy matched' if matched else 'File fingerprint ready; no approved match',metrics)
            self.attempts[key]=(2,float('inf'))
            self.ready[key]=(anchors,metrics,bool(matched))
            self.status_due=now+5
            if sharing(self.addon):
                from resources.lib.playback.contributions import enrich_pending
                try:
                    enrich_pending(self.addon,context)
                except TimingError:
                    pass
        except (range_identity.IdentityError,OSError,ValueError,TypeError,KeyError) as error:
            # Never display raw exception text, addresses or authorization details.
            code=str(error) if isinstance(error,range_identity.IdentityError) else 'identity_unavailable'
            allowed={'playback_changed_or_buffering','unsupported_selected_file','identity_time_limit','range_request_unavailable',
                     'strict_ranges_required','invalid_content_range','invalid_range_length','file_changed','file_validator_changed',
                     'unsafe_redirect','redirect_limit','identity_read_limit','truncated_range','identity_unavailable'}
            allowed.add('low_information_samples')
            self.status(code if code in allowed else 'identity_unavailable')


def manage(addon):
    labels=['Refresh shared timings','Recheck the playing file','Identification status','Back']
    selected=xbmcgui.Dialog().select('Shared timings',labels)
    if selected==0:
        result=shared_catalogue.refresh(addon,force=True)
        xbmcgui.Dialog().notification('Shared timings',result)
    elif selected==1:
        if not owned():
            xbmcgui.Dialog().ok('Shared timings','Start an episode in MDM Flix first.')
            return
        xbmcgui.Window(10000).setProperty(RESET,str(time.time_ns()))
        xbmcgui.Dialog().notification('Shared timings','Playing file queued for a background recheck.')
    elif selected==2:
        text='No file check has completed yet.'
        try:
            path=Path(xbmcvfs.translatePath(addon.getAddonInfo('profile')))/'native_cut_status.json'
            with path.open(encoding='utf8') as stream:
                raw=stream.read(4097)
            row=json.loads(raw) if len(raw)<=4096 else {}
            if row.get('schema')==1 and isinstance(row.get('status'),str):
                text='Last check: '+row['status'][:100]
                m=row.get('metrics',{})
                if all(type(m.get(k)) in (int,float) for k in ('bytes','requests','seconds')):
                    text+='\n{} KiB · {} requests · {:.2f}s'.format(round(m['bytes']/1024,1),m['requests'],m['seconds'])
        except (OSError,ValueError,TypeError,KeyError):
            pass
        xbmcgui.Dialog().ok('Shared timings',text+'\nThis checks known file copies. Audio/chapter timing methods remain available. Differently encoded or edited files may need their own reviewed identity.')


def start(addon,monitor):
    def run():
        worker=Worker(addon,abort=monitor.abortRequested)
        while not monitor.waitForAbort(1):
            try:
                worker.tick()
            except (OSError,ValueError,TypeError,KeyError,RuntimeError):
                pass
    thread=threading.Thread(target=run,name='MDM-CutIdentity',daemon=True)
    thread.start()
    return thread
