"""Sequential, budgeted release comparison. Resolved URLs stay in memory."""
import json
import os
import tempfile
import time
import uuid
import re
import sqlite3
import xbmcvfs
from mdmlink import autoplay_context
from mdmlink.errors import PlaybackError,Cancelled,SourceFailure,SourceNotReady,SourcePreparing,AutoplayBudgetExpired
from resources.lib.playback import timing_rules as r,timing_match as policy
from resources.lib.playback.match_lookup import Lookup
from resources.lib.playback.media_metadata import Cache,active
from resources.lib.playback.chapter_facts import fingerprint
from resources.lib.playback.episode_policy import chapter_marks

def limit(addon):
    value=addon.getSetting('episode_match_candidates') or '5'
    return int(value) if value in ('3','5','8') else 5
def budget(addon):
    value=addon.getSetting('episode_match_budget') or '30'
    return int(value) if value in ('15','30','45') else 30
def path(addon):return os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')),'last_timing_match.json')
def write(addon,report):
    temporary=None
    try:
        destination=path(addon);os.makedirs(os.path.dirname(destination),exist_ok=True)
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=os.path.dirname(destination),prefix='.mdm-match-',delete=False) as stream:
            temporary=stream.name;json.dump(report,stream,allow_nan=False)
        os.replace(temporary,destination);return True
    except (OSError,ValueError,TypeError):return False
    finally:
        if temporary and os.path.exists(temporary):
            try:os.remove(temporary)
            except OSError:pass
def read(addon):
    try:
        with open(path(addon),encoding='utf-8') as stream:raw=stream.read(65537)
        data=json.loads(raw)
        return data if len(raw)<=65536 and data.get('schema')==1 else {}
    except (OSError,ValueError,AttributeError):return {}

def history_path(addon):return os.path.join(os.path.dirname(path(addon)),'timing_match_history.sqlite')

def archive(addon,report):
    db=None
    try:
        raw=json.dumps(report,allow_nan=False)
        if len(raw)>65536:return
        os.makedirs(os.path.dirname(history_path(addon)),exist_ok=True)
        db=sqlite3.connect(history_path(addon),timeout=.2)
        if db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):return
        db.execute('CREATE TABLE IF NOT EXISTS reports (run TEXT PRIMARY KEY,value TEXT,updated REAL)');db.execute('PRAGMA user_version=1')
        db.execute('INSERT OR REPLACE INTO reports VALUES(?,?,?)',(report['run_id'],raw,time.time()))
        db.execute('DELETE FROM reports WHERE run IN (SELECT run FROM reports ORDER BY updated DESC,run LIMIT -1 OFFSET 20)');db.commit()
    except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):pass
    finally:
        if db:db.close()

def history(addon):
    db=None
    try:
        db=sqlite3.connect('file:'+history_path(addon).replace('\\','/')+'?mode=ro',uri=True,timeout=.2)
        if db.execute('PRAGMA user_version').fetchone()[0]!=1:return []
        result=[]
        for raw, in db.execute('SELECT value FROM reports ORDER BY updated DESC,run LIMIT 20'):
            if len(raw)<=65536:
                try:
                    value=json.loads(raw)
                    if isinstance(value,dict) and value.get('schema')==1:result.append(value)
                except ValueError:pass
        return result
    except (OSError,sqlite3.Error,ValueError):return []
    finally:
        if db:db.close()

def failure_detail(entry,error):
    code=getattr(error,'ad_error_code',None)
    if isinstance(code,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',code):entry['service_error_code']=code
    scope=getattr(error,'ad_error_scope',None)
    if scope in ('source','service'):entry['service_error_scope']=scope

def compare(addon,rows,resolve,cancel=lambda:False,lookup=None,update=lambda message:None,search_seconds=0):
    start=time.monotonic();deadline=start+budget(addon);maximum=limit(addon)
    report=dict(schema=1,run_id=uuid.uuid4().hex[:12],updated_utc=int(time.time()),status='checking',attempted=0,failed=0,not_ready=0,rejected=0,unknown=0,duplicates=0,elapsed_seconds=0,lookup_calls=0,candidates=[],selected=None,search_seconds=round(search_seconds,3),total_seconds=0)
    ready=[];seen=set();item=None;lookup_obj=None
    def finish(status):
        report.update(status=status,elapsed_seconds=round(time.monotonic()-start,3),total_seconds=round(search_seconds+time.monotonic()-start,3),lookup_calls=lookup_obj.calls if lookup_obj else 0)
        report['timing_hits']=len(lookup_obj.rows) if lookup_obj else 0
        write(addon,report);archive(addon,report)
    try:
        with autoplay_context.bounded(budget(addon)):
            for source in rows:
                if cancel():raise Cancelled('Playback cancelled.')
                if report['attempted']>=maximum or time.monotonic()>=deadline:break
                autoplay_context.check()
                from resources.lib import device_policy,connection_policy
                if not device_policy.allows(addon,source) or not connection_policy.allows(addon,source):continue
                identity=fingerprint(source)
                if identity in seen:report['duplicates']+=1;continue
                seen.add(identity)
                candidate_item=(source.get('extra') or {}).get('item') or {}
                candidate_identity=r.identity(candidate_item)
                if not candidate_identity:continue
                if item is None:
                    item=candidate_identity;report['episode']={key:item[key] for key in ('tmdb_id','season','episode')}
                    lookup_obj=lookup or Lookup(addon,item,deadline,cancel);lookup_obj.prime()
                elif r.key(candidate_identity)!=r.key(item):continue
                report['attempted']+=1;index=report['attempted'];update('Checking timing match {} of {}'.format(index,maximum))
                entry=dict(candidate=index,status='checking',runtime=None,reason='pending',score=0,seconds=0)
                report['candidates'].append(entry);tick=time.monotonic();finish('checking')
                extra=source.get('extra') or {}
                known=r.source_duration(source) if extra.get('file_duration_origin') in ('header','observed') else None
                if known:lookup_obj.measured(known)
                if known and policy.assess(lookup_obj.rows,known,mode=r.policy(addon))['status']=='mismatch':
                    cached=Cache(addon).get(identity) if active(addon) else None
                    cached_marks=chapter_marks(cached['chapters'],known) if cached and cached['status']=='ready' and abs(cached['duration']-known)<=2 and addon.getSetting('episode_prefer_chapters')!='false' else []
                    checked=policy.assess(lookup_obj.rows,known,cached_marks,r.policy(addon))
                    if checked['status']=='mismatch':
                        entry.update(status='mismatch',reason=checked['reason'],runtime=known,cached=True)
                        report['rejected']+=1;continue
                try:url=resolve(source,attempt=(index,maximum))
                except SourceNotReady as error:
                    failure_detail(entry,error)
                    report['not_ready']+=1;entry.update(status='not_ready',reason='release_preparing',seconds=round(time.monotonic()-tick,3));continue
                except SourceFailure as error:
                    failure_detail(entry,error)
                    report['failed']+=1;entry.update(status='failed',reason='source_failed',seconds=round(time.monotonic()-tick,3));continue
                except PlaybackError as error:
                    failure_detail(entry,error)
                    entry.update(status='stopped',reason='service_error',seconds=round(time.monotonic()-tick,3))
                    raise
                if cancel():raise Cancelled('Playback cancelled.')
                duration=r.source_duration(source) if (source.get('extra') or {}).get('file_duration_origin') in ('header','observed') else None
                value=Cache(addon).get(identity) if active(addon) else None
                marks=chapter_marks(value['chapters'],duration) if value and value['status']=='ready' and duration and abs(value['duration']-duration)<=2 and addon.getSetting('episode_prefer_chapters')!='false' else []
                timings=lookup_obj.measured(duration) if duration else lookup_obj.rows
                result=policy.assess(timings,duration,marks,r.policy(addon))
                beyond=[r.number(row.get('end')) for row in timings if row.get('kind')=='outro' and r.number(row.get('end')) is not None and duration and row['end']>duration]
                if beyond:entry['rejected_outro_end']=max(beyond)
                entry.update(status=result['status'],reason=result['reason'],runtime=duration,score=result['score'],seconds=round(time.monotonic()-tick,3))
                entry['provider']=result.get('provider') if result.get('provider') in ('IntroDB','TheIntroDB') else None
                entry['runtime_difference']=result.get('delta')
                for kind in ('intro','outro'):
                    chosen=result.get(kind)
                    if chosen:entry[kind]={'start':chosen['range'][0],'end':chosen['range'][1]}
                if result['status']=='mismatch':report['rejected']+=1;continue
                if result['status']=='unknown':report['unknown']+=1
                ready.append((source,url,result,index))
                # Labelled file intro, or a close runtime + intro/outro pair,
                # is a sufficient match to avoid unnecessary extra preparation.
                if result['score']>=100:break
            if cancel():raise Cancelled('Playback cancelled.')
    except AutoplayBudgetExpired:
        # Keep a successfully checked candidate if the comparison time expires.
        pass
    except Cancelled:
        finish('cancelled');raise
    except SourcePreparing:
        finish('preparing');raise
    except PlaybackError:
        finish('stopped');raise
    except Exception:
        finish('failed');raise
    from resources.lib import device_policy,connection_policy
    ready=[entry for entry in ready if device_policy.allows(addon,entry[0]) and connection_policy.allows(addon,entry[0])]
    if not ready:finish('no_match');return None
    source,url,result,index=max(ready,key=lambda entry:(entry[2]['score']>=70,bool(entry[0].get('debrid')),entry[2]['score'],-entry[2]['delta'] if entry[2].get('delta') is not None else -86400,-entry[2]['end_gap'] if entry[2].get('end_gap') is not None else -86400,-entry[3]))
    report['selected']=index;finish('matched' if result['score']>=70 else 'partial' if result['score'] else 'unverified')
    return source,url,result,report

def text(addon):
    report=read(addon)
    if not report:return 'No automatic timing-match check recorded yet.'
    lines=['Timing match: {} · {:.1f}s · checked {}, rejected {}, not ready {}'.format(report['status'],report['elapsed_seconds'],report['attempted'],report['rejected'],report['not_ready'])]
    lines.append('Provider search {:.1f}s · matching {:.1f}s · total to selection {:.1f}s (not playback confirmation)'.format(report.get('search_seconds',0),report['elapsed_seconds'],report.get('total_seconds',report['elapsed_seconds'])))
    if report.get('episode'):lines.append('Episode: TMDB {tmdb_id} · S{season:02d}E{episode:02d}'.format(**report['episode']))
    lines.append('Chosen candidate: '+str(report.get('selected') or 'none'))
    lines.append('Timing rows available: {} · public lookup requests: {}'.format(report.get('timing_hits',0),report.get('lookup_calls',0)))
    for row in report.get('candidates',[]):
        lines.append('#{}: {} · runtime {}s · {} · {:.1f}s'.format(row['candidate'],row['status'],row['runtime'] if row['runtime'] is not None else 'unknown',row['reason'].replace('_',' '),row['seconds']))
        if row.get('rejected_outro_end') is not None:lines.append('Reported outro end {}s exceeds this file.'.format(row['rejected_outro_end']))
        if row.get('service_error_code'):lines.append('AllDebrid: '+row['service_error_code']+' ('+row.get('service_error_scope','service')+')')
        for kind in ('intro','outro'):
            if row.get(kind):lines.append('{}: {:.1f}–{:.1f}s · {}'.format(kind.title(),row[kind]['start'],row[kind]['end'],row.get('provider') or 'file'))
    lines.append('A bounds/runtime match is not content verification. Unverified means no timing match was established.')
    recent=history(addon)
    if recent:
        lines.append('Recent matching attempts (latest 20 retained):')
        for previous in recent[:5]:
            episode=previous.get('episode') or {};codes=[row.get('service_error_code') for row in previous.get('candidates',[]) if row.get('service_error_code')]
            lines.append('S{}E{} · {} · {} candidates{}'.format(episode.get('season','?'),episode.get('episode','?'),previous.get('status','unknown'),previous.get('attempted',0),' · '+', '.join(codes) if codes else ''))
    return '\n\n'.join(lines)
