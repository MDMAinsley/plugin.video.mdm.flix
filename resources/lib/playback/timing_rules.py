"""Pure identity, segment and runtime matching. No network or player access."""
import hashlib
import json
import math
import re


def number(value,low=0,high=86400):
    return float(value) if type(value) in (int,float) and math.isfinite(value) and low<=value<=high else None


def positive(value):return value if type(value) is int and 0<value<2147483647 else None


def identity(item):
    if not isinstance(item,dict) or item.get('media_type')!='episode':return None
    tmdb=positive(item.get('tmdb_id'));season=item.get('season');episode=positive(item.get('episode'))
    if not tmdb or type(season) is not int or not 0<=season<10000 or not episode:return None
    extra=item.get('extra');extra=extra if isinstance(extra,dict) else {}
    ids=extra.get('timing_identity');ids=ids if isinstance(ids,dict) else {}
    result={'tmdb_id':tmdb,'season':season,'episode':episode,'media_type':'episode',
            'title':str(item.get('title') or 'Episode')[:200], 'catalog_runtime':number(item.get('duration_seconds')) or number(item.get('catalog_runtime')) or 0}
    imdb=ids.get('imdb_id') or item.get('imdb_id')
    if isinstance(imdb,str) and re.fullmatch(r'tt[0-9]{5,12}',imdb):result['imdb_id']=imdb
    for name in ('tvdb_id','tvdb_episode_id'):
        value=ids.get(name) or item.get(name)
        if positive(value):result[name]=value
    return result


def clean_identity(value):
    if not isinstance(value,dict):return None
    item=dict(value,extra={'timing_identity':{k:value.get(k) for k in ('imdb_id','tvdb_id','tvdb_episode_id')}})
    item['duration_seconds']=value.get('catalog_runtime')
    return identity(item)


def key(item):
    item=clean_identity(item)
    return hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest() if item else None


def tidb_query(item):
    result={'tmdb_id':item['tmdb_id'],'season':item['season'],'episode':item['episode'],
            'episode_name':item['title'],'merge_unknown':'false','details':'true'}
    for name in ('tvdb_id','tvdb_episode_id'):
        if item.get(name):result[name]=item[name]
    return result


def versions(body,item):
    if not tidb_identity(body,item):return []
    rows=body.get('versions')
    if not isinstance(rows,list):return []
    result=[]
    for row in rows[:100]:
        if not isinstance(row,dict):continue
        duration=number(row.get('duration_ms'),60000,86400000)
        if duration and duration/1000 not in result:result.append(duration/1000)
    return result


def tidb_identity(body,item):
    return (isinstance(body,dict) and body.get('type')=='tv' and positive(body.get('tvdb_id')) is not None
            and (not item.get('tvdb_id') or body['tvdb_id']==item['tvdb_id'])
            and type(body.get('season')) is int and type(body.get('episode')) is int
            and body.get('season')==item['season'] and body.get('episode')==item['episode'])


def parse_tidb(body,item):
    if not tidb_identity(body,item):return []
    duration=number(body.get('group_duration_ms'),60000,86400000)
    duration=duration/1000 if duration else None
    pinned=bool(item.get('tvdb_id') and item.get('tvdb_episode_id'))
    result=[]
    for field,kind in (('intro','intro'),('credits','outro')):
        rows=body.get(field,[])
        if not isinstance(rows,list):continue
        for row in rows[:10]:
            if not isinstance(row,dict):continue
            start=0 if row.get('start_ms') is None and kind=='intro' else number(row.get('start_ms'),0,86400000)
            end=number(row.get('end_ms'),0,86400000)
            if start is None or end is None and kind=='intro':continue
            if end is not None and end<=start:continue
            result.append(dict(provider='TheIntroDB',kind=kind,start=start/1000,end=end/1000 if end is not None else None,
                               runtime=duration,confidence=number(row.get('confidence'),0,1) or 0,
                               count=positive(row.get('submission_count')) or 0,pinned=pinned))
    return result


def parse_introdb(body,item):
    if (not isinstance(body,dict) or body.get('imdb_id')!=item.get('imdb_id') or not item.get('imdb_id')
        or body.get('season')!=item['season'] or body.get('episode')!=item['episode'] or body.get('is_movie') is True):return []
    result=[]
    for kind in ('intro','outro'):
        row=body.get(kind)
        if not isinstance(row,dict):continue
        start=number(row.get('start_sec'));end=number(row.get('end_sec'))
        if start is None or end is None or end<=start:continue
        result.append(dict(provider='IntroDB',kind=kind,start=start,end=end,runtime=None,
                           confidence=number(row.get('confidence'),0,1) or 0,count=positive(row.get('submission_count')) or 0,pinned=False))
    return result


def interval(row,duration):
    duration=number(duration,60)
    if not duration or not isinstance(row,dict):return None
    start=number(row.get('start'));end=duration if row.get('end') is None and row.get('kind')=='outro' else number(row.get('end'))
    if start is None or end is None or not 0<=start<end<=duration:return None
    if row.get('kind')=='intro':
        if start>=min(900,duration*.5) or not 3<=end-start<=600 or end>=duration-30:return None
    elif row.get('kind')=='outro':
        if start<duration*.5 or not 3<=end-start<=900:return None
    else:return None
    return start,end


def match(rows,duration,kind):
    """Only tight runtime + pinned-episode + supported data; never rescale times."""
    duration=number(duration,60)
    if not duration:return None,'Actual file runtime unknown'
    blocked={group(row) for row in rows if isinstance(row,dict) and outro_mismatch([row],duration)}
    valid=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('kind')!=kind or group(row) in blocked:continue
        runtime=number(row.get('runtime'),60)
        bounds=interval(row,duration)
        confidence=number(row.get('confidence'),0,1)
        count=row.get('count')
        if (bounds and runtime and abs(runtime-duration)<=5 and row.get('pinned') is True
            and confidence is not None and confidence>=.8 and type(count) is int and count>=2):
            valid.append((abs(runtime-duration),-confidence,-count,row,bounds))
    if not valid:return None,'No supported episode/runtime match'
    valid.sort(key=lambda value:value[:3]);best=valid[0]
    for other in valid[1:]:
        if other[0]-best[0]<2 and any(abs(a-b)>2 for a,b in zip(other[4],best[4])):
            return None,'Conflicting timings for similar runtimes'
    return dict(best[3],range=best[4],delta=best[0]),'Runtime match (not edit verification)'


def source_duration(row):
    extra=row.get('extra') or {}
    # Catalogue runtime and pack duration are deliberately excluded.
    return number(extra.get('file_duration_seconds'),60)


def policy(addon):
    value=addon.getSetting('episode_timing_policy')
    return 'Best available' if value in ('','Best available') else 'Strict matches'


def fallback_interval(row,duration):
    """A reported outro beyond EOF is a mismatch, never truncated to fit."""
    return interval(row,duration)

def group(row):return row.get('provider') if isinstance(row.get('provider'),str) else 'Unknown',number(row.get('runtime'),60)

def outro_mismatch(rows,duration):
    length=number(duration,60)
    if not length:return False
    for row in rows:
        if not isinstance(row,dict) or row.get('kind')!='outro':continue
        start=number(row.get('start'));end=number(row.get('end'))
        if start is not None and start>=length or end is not None and end>length:return True
    return False


def choose(rows,duration,kind,mode='Best available'):
    chosen,reason=match(rows,duration,kind)
    if chosen:return dict(chosen,unverified=False),reason
    if mode!='Best available':return None,reason
    duration=number(duration,60)
    if not duration:return None,'Actual playing runtime unavailable'
    blocked={group(row) for row in rows if isinstance(row,dict) and outro_mismatch([row],duration)}
    options=[]
    for row in rows:
        if not isinstance(row,dict) or row.get('kind')!=kind or group(row) in blocked:continue
        bounds=fallback_interval(row,duration)
        if not bounds:continue
        runtime=number(row.get('runtime'),60);delta=abs(runtime-duration) if runtime else None
        confidence=number(row.get('confidence'),0,1) or 0
        count=row.get('count');count=count if type(count) is int and count>=0 else 0
        # Known release duration first, closest to the actual file; unknown
        # runtime candidates use the available confidence/report information.
        score=(runtime is None,delta if delta is not None else 0,-confidence,-count,not row.get('pinned',False))
        options.append((score,row,bounds,delta))
    if not options:return None,'No usable intro/outro timing hit'
    options.sort(key=lambda entry:entry[0]);_,row,bounds,delta=options[0]
    return dict(row,range=bounds,delta=delta,unverified=True),'Best available fallback (unverified)'
