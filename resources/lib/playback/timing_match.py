"""Pure release matching: keep intro/outro from the same service/version."""
from resources.lib.playback import timing_rules as r
from resources.lib.playback.episode_policy import INTRO,CREDITS,chapter_intro

def assess(rows,duration,chapters=(),mode='Best available'):
    duration=r.number(duration,60)
    unknown=dict(status='unknown',score=0,reason='runtime_unknown',intro=None,outro=None,delta=None,provider=None,end_gap=None)
    if not duration:return unknown
    intro=chapter_intro(chapters,duration);outro=None
    for index,(at,name) in enumerate(chapters):
        if name in CREDITS and r.interval(dict(kind='outro',start=at,end=None),duration):outro=(at,duration)
    if intro:return dict(unknown,status='chapters',score=120 if outro else 110,reason='labelled_chapters',chapter_intro=intro,chapter_outro=outro)
    groups={}
    for row in rows:
        if isinstance(row,dict) and row.get('kind') in ('intro','outro'):
            groups.setdefault(r.group(row),[]).append(row)
    results=[];rejected=False;rejection='no_usable_intro'
    for group,entries in groups.items():
        if r.outro_mismatch(entries,duration):rejected=True;rejection='outro_past_file';continue
        if group[1] is not None and abs(group[1]-duration)>5:rejected=True;rejection='runtime_difference';continue
        chosen_intro,_=r.choose(entries,duration,'intro',mode)
        chosen_outro,_=r.choose(entries,duration,'outro',mode)
        if not chosen_intro:
            if chosen_outro:results.append(dict(status='outro_only',score=20,reason='outro_bounds',intro=None,outro=chosen_outro,delta=chosen_outro.get('delta'),provider=group[0],end_gap=duration-chosen_outro['range'][1]))
            continue
        if chosen_outro and chosen_intro['range'][1]>chosen_outro['range'][0]:rejected=True;rejection='overlapping_markers';continue
        delta=chosen_intro.get('delta');known=r.number(chosen_intro.get('runtime'),60)
        tight=known is not None and delta is not None and delta<=5
        score=(90 if tight else 70)+(10 if chosen_outro else 0)
        gap=duration-chosen_outro['range'][1] if chosen_outro and chosen_outro.get('end') is not None else None
        results.append(dict(status='matched',score=score,reason='runtime_and_bounds' if tight else 'marker_bounds',intro=chosen_intro,outro=chosen_outro,delta=delta,provider=group[0],end_gap=gap))
    if results:return max(results,key=lambda value:(value['score'],-value['delta'] if value['delta'] is not None else -86400,-value['end_gap'] if value['end_gap'] is not None else -86400))
    return dict(unknown,status='mismatch' if rejected else 'unknown',reason=rejection)

def enabled(addon):return addon.getSetting('episode_stream_matching')!='false'

def order(addon,rows):
    if not enabled(addon):return rows
    from resources.lib.playback.timing_store import Store,TimingError
    from resources.lib.playback.media_metadata import Cache,active
    from resources.lib.playback.chapter_facts import fingerprint
    from resources.lib.playback.episode_policy import chapter_marks
    memo={};store=Store(addon);cache=Cache(addon).get_many([fingerprint(row) for row in rows]) if active(addon) else {}
    result=[]
    for row in rows:
        extra={k:v for k,v in (row.get('extra') or {}).items() if k not in ('timing_fit','timing_fit_reason','timing_fit_score')}
        item=r.identity(extra.get('item'));duration=r.source_duration(row)
        if item:
            key=r.key(item)
            if key not in memo:
                try:memo[key]=store.data(item)[0] if addon.getSetting('episode_timing_lookup')!='false' else []
                except TimingError:memo[key]=[]
            value=cache.get(fingerprint(row));marks=[]
            if value and value['status']=='ready' and duration and abs(value['duration']-duration)<=2 and addon.getSetting('episode_prefer_chapters')!='false':marks=chapter_marks(value['chapters'],duration)
            match=assess(memo[key],duration,marks,r.policy(addon))
            extra.update(timing_fit=match['status'],timing_fit_score=match['score'],timing_fit_reason=match['reason'])
        result.append(dict(row,extra=extra))
    return sorted(result,key=lambda row:((row.get('extra') or {}).get('timing_fit_score',0)>=70,(row.get('extra') or {}).get('timing_fit')!='mismatch',bool(row.get('debrid')),(row.get('extra') or {}).get('timing_fit_score',0)),reverse=True)
