"""Timing provenance and deliberate corrections for the exact playing release."""
import json
import xbmc
import xbmcgui
from resources.lib.playback import audio_timing, timing_rules as rules,timing_service
from resources.lib.playback.timing_store import Store,TimingError
from resources.lib.playback.episode_policy import timing,EpisodeError,chapter_intro,chapter_marks
from resources.lib.playback.episode_controls import current_token, read_chapters
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
        return dict(item=item,token=token,fingerprint=fingerprint,duration=duration,
                    audio_file=audio_timing.file_digest(player))
    except (ValueError,RuntimeError,AttributeError):return None


def same(context):
    now=playing(context['item'])
    return bool(now and now['token']==context['token'] and now['fingerprint']==context['fingerprint'] and now['audio_file']==context['audio_file'] and abs(now['duration']-context['duration'])<=5)


def save_intro(store, context):
    values = []
    for label in ('Intro starts (seconds or M:SS)', 'Intro ends (seconds or M:SS)'):
        raw = xbmcgui.Dialog().input(label, type=xbmcgui.INPUT_ALPHANUM)
        if raw == '' or not same(context):
            return
        values.append(timing(raw))
    row = dict(kind='intro', start=values[0], end=values[1])
    store.confirm(context['fingerprint'], row, context['duration'])
    xbmcgui.Dialog().notification('Intro timings', 'Corrected times saved for this file.')


def mark_playing_intro(addon, token):
    context = playing()
    if not context or context['token'] != token:
        return
    try:
        save_intro(Store(addon), context)
    except (TimingError, EpisodeError) as error:
        xbmcgui.Dialog().ok('Intro timings', str(error))


def details(item,rows,status,duration,mode='Strict matches'):
    lines=['{} · S{:02d}E{:02d}'.format(item['title'],item['season'],item['episode']),
           'File runtime: '+(stamp(duration) if duration else 'unknown (not taken from TMDB)'),
           'Labelled file chapters remain first when preferred. Runtime matching is not proof of an identical edit.',
           'Timing policy: '+mode+'. Best available uses a valid service hit even without release-runtime evidence; fallback timings are unverified.']
    lines.extend(status or ['Background lookup queued; check again in a few seconds.'])
    from resources.lib.playback.timing_match import assess
    pair=assess(rows,duration,mode=mode)
    for kind in ('intro','outro'):
        chosen=pair.get(kind);reason=pair['reason'].replace('_',' ')
        lines.append(kind.title()+': '+(chosen['provider']+' · '+stamp(chosen['start'])+'–'+stamp(chosen['end'])+' · '+reason if chosen else reason))
    for row in rows:
        fits=rules.fallback_interval(row,duration) if duration else None
        note=' · outside this file' if duration and not fits else ''
        if duration and row['kind']=='outro' and row.get('end') is not None and row['end']>duration:note=' · outro past EOF: this timing group is rejected for this file'
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
            from resources.lib.playback.stream_match import text as match_text
            status.append(match_text(addon))
            labels=['Timing information / why a suggestion is not used','Check again','Save corrected intro times for this playing file…','Clear confirmed timings for this playing file']
            suggestions=[row for row in rows if duration and rules.fallback_interval(row,duration)]
            audio = audio_timing.suggestion(addon, context['audio_file'], item, duration) if context else None
            if audio:
                suggestions.append(audio)
            saved_audio = audio_timing.saved_suggestion(addon, item) if not audio else None
            labels.extend('Review '+row['kind']+' suggestion: '+stamp(row['start'])+'–'+stamp(row['end'])+' · '+row['provider'] for row in suggestions)
            if saved_audio:
                labels.append('View saved audio intro suggestion')
            marking_index=len(labels)
            labels.extend(('Mark intro using playback / continue draft','Mark outro using playback / continue draft'))
            selected=xbmcgui.Dialog().select('Intro / outro timings',labels)
            if selected<0:return
            if selected in (marking_index,marking_index+1):
                if not context or not same(context):
                    xbmcgui.Dialog().ok('Mark timing','Start this episode before marking its playing file.');return
                from resources.lib.playback.marking import panel
                panel(addon,context['token'],'intro' if selected==marking_index else 'outro')
                return
            if selected==0:xbmcgui.Dialog().textviewer('Intro / outro timings',details(item,rows,status,duration,rules.policy(addon)));continue
            if selected==1:
                timing_service.enqueue(addon,item,duration);continue
            if saved_audio and selected == 4 + len(suggestions):
                text = 'Audio match: {}–{}. This result is from a previously scanned file. Play the matching file to review it for Skip Intro.'.format(
                    stamp(saved_audio['start']), stamp(saved_audio['end']))
                xbmcgui.Dialog().textviewer('Saved audio intro suggestion', text)
                continue
            if not context or not same(context):
                xbmcgui.Dialog().ok('Intro / outro timings','Play this episode before confirming timings for its exact file.');return
            if selected==2:
                save_intro(store, context);return
            if selected==3:
                store.clear_confirmation(context['fingerprint'])
                key = audio_timing.confirmation_key(context['audio_file'], item)
                if key:
                    store.clear_confirmation(key)
                xbmcgui.Dialog().notification('Intro timings','Confirmed timings cleared for this file.');return
            if not 0<=selected-4<len(suggestions):return
            row=suggestions[selected-4]
            if row['provider'] == 'Audio match':
                chapter_range = chapter_intro(chapter_marks(read_chapters(), duration), duration)
                if chapter_range and any(abs(value - bound) > 3 for value, bound in
                                         zip((row['start'], row['end']), chapter_range)):
                    xbmcgui.Dialog().ok(
                        'Audio and chapter timings differ',
                        'Audio suggests {}–{}. File chapters mark {}–{}. Review the scene cut before saving a correction.'.format(
                            stamp(row['start']), stamp(row['end']), stamp(chapter_range[0]), stamp(chapter_range[1])))
                    continue
            text='{} suggests {}–{}. Confirm only if you checked that this matches the playing file. This will not change your show preset or submit anything online.'.format(row['provider'],stamp(row['start']),stamp(row['end']))
            if xbmcgui.Dialog().yesno('Use this timing for this file?',text) and same(context):
                key = context['fingerprint']
                if row['provider'] == 'Audio match':
                    key = audio_timing.confirmation_key(context['audio_file'], item)
                store.confirm(key,row,duration)
                xbmcgui.Dialog().notification('Intro timings','Timing saved for this file.');return
    except (TimingError,EpisodeError,CatalogueError) as error:xbmcgui.Dialog().ok('Intro / outro timings',str(error))
