"""Timing provenance and deliberate corrections for the exact playing release."""
import json
import xbmc
import xbmcgui
from resources.lib.playback import timing_rules as rules,timing_service
from resources.lib.playback.timing_store import Store,TimingError
from resources.lib.playback.episode_policy import timing,EpisodeError
from resources.lib.playback.episode_controls import current_token
from resources.lib.playback.tracking import PROPERTY
from resources.lib.catalogue.tmdb import CatalogueError,number


def stamp(value):
    if value is None:return 'end'
    value=int(value);return '{}:{:02d}'.format(value//60,value%60)


def playing(expected=None):
    try:
        player=xbmc.Player();token=current_token(player)
        if not token:return None
        payload=json.loads(player.getPlayingItem().getProperty(PROPERTY));item=rules.clean_identity(payload.get('timing'))
        fingerprint=payload.get('chapter_key');duration=rules.number(player.getTotalTime(),60)
        import re
        if not item or not duration or not isinstance(fingerprint,str) or not re.fullmatch('[0-9a-f]{64}',fingerprint):return None
        if expected and any(item[k]!=expected[k] for k in ('tmdb_id','season','episode')):return None
        return dict(item=item,token=token,fingerprint=fingerprint,duration=duration)
    except (ValueError,RuntimeError,AttributeError):return None


def same(context):
    now=playing(context['item'])
    return bool(now and now['token']==context['token'] and now['fingerprint']==context['fingerprint'] and abs(now['duration']-context['duration'])<=5)


def details(item,rows,status,duration,mode='Strict matches'):
    lines=['{} · S{:02d}E{:02d}'.format(item['title'],item['season'],item['episode']),
           'File runtime: '+(stamp(duration) if duration else 'unknown (not taken from TMDB)'),
           'Labelled file chapters remain first when preferred. Runtime matching is not proof of an identical edit.',
           'Timing policy: '+mode+'. Best available uses a valid service hit even without release-runtime evidence; fallback timings are unverified.']
    lines.extend(status or ['Background lookup queued; check again in a few seconds.'])
    for kind in ('intro','outro'):
        chosen,reason=rules.choose(rows,duration,kind,mode)
        lines.append(kind.title()+': '+(chosen['provider']+' · '+stamp(chosen['start'])+'–'+stamp(chosen['end'])+' · '+reason if chosen else reason))
    for row in rows:
        fits=rules.fallback_interval(row,duration) if duration else None
        note=' · outside this file' if duration and not fits else ''
        if duration and fits and row['kind']=='outro' and row.get('end') is not None and row['end']>duration:note=' · outro end past EOF; Next episode uses its start only'
        lines.append('{} {}: {}–{} · {} reports · release runtime {}{}'.format(row['provider'],row['kind'],stamp(row['start']),stamp(row['end']),row['count'],stamp(row['runtime']) if row['runtime'] else 'unknown',note))
    return '\n\n'.join(lines)


def action(addon,core,params):
    try:
        context=playing();item=None;duration=0
        if 'tmdb_id' in params:
            expected={name:number(params.get(name),1 if name in ('tmdb_id','episode') else 0) for name in ('tmdb_id','season','episode')}
            context=playing(expected)
        else:expected=None
        if context:item=context['item'];duration=context['duration']
        elif expected:
            from resources.lib.catalogue.playback_item import load
            item=rules.identity(load(addon,core,dict(expected,media_type='episode')))
        if not item:
            xbmcgui.Dialog().ok('Intro / outro timings','Open this from an episode’s hold/menu options, or start an MDM episode first.');return
        store=Store(addon);timing_service.enqueue(addon,item,duration)
        while True:
            rows,status=store.data(item)
            if not timing_service.enabled(addon):status=['Online timing lookups are off. Confirmed local timings and show presets remain separate.']
            if context:
                from resources.lib.playback.media_metadata import description
                status.append(description(addon,context['fingerprint']))
            labels=['Timing information / why a suggestion is not used','Check again','Save corrected intro times for this playing file…','Clear confirmed timings for this playing file']
            suggestions=[row for row in rows if duration and rules.fallback_interval(row,duration)]
            labels.extend('Review '+row['kind']+' suggestion: '+stamp(row['start'])+'–'+stamp(row['end'])+' · '+row['provider'] for row in suggestions)
            selected=xbmcgui.Dialog().select('Intro / outro timings',labels)
            if selected<0:return
            if selected==0:xbmcgui.Dialog().textviewer('Intro / outro timings',details(item,rows,status,duration,rules.policy(addon)));continue
            if selected==1:
                timing_service.enqueue(addon,item,duration);continue
            if not context or not same(context):
                xbmcgui.Dialog().ok('Intro / outro timings','Play this episode before confirming timings for its exact file.');return
            if selected==2:
                values=[]
                for label in ('Intro starts (seconds or M:SS)','Intro ends (seconds or M:SS)'):
                    raw=xbmcgui.Dialog().input(label,type=xbmcgui.INPUT_ALPHANUM)
                    if raw=='':return
                    values.append(timing(raw))
                row=dict(kind='intro',start=values[0],end=values[1])
                if not same(context):return
                store.confirm(context['fingerprint'],row,duration)
                xbmcgui.Dialog().notification('Intro timings','Corrected times saved for this file.');return
            if selected==3:
                store.clear_confirmation(context['fingerprint'])
                xbmcgui.Dialog().notification('Intro timings','Confirmed timings cleared for this file.');return
            if not 0<=selected-4<len(suggestions):return
            row=suggestions[selected-4]
            text='{} suggests {}–{}. Confirm only if you checked that this matches the playing file. This will not change your show preset or submit anything online.'.format(row['provider'],stamp(row['start']),stamp(row['end']))
            if xbmcgui.Dialog().yesno('Use this timing for this file?',text) and same(context):
                store.confirm(context['fingerprint'],row,duration)
                xbmcgui.Dialog().notification('Intro timings','Timing saved for this file.');return
    except (TimingError,EpisodeError,CatalogueError) as error:xbmcgui.Dialog().ok('Intro / outro timings',str(error))
