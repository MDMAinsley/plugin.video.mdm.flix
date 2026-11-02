"""Release/episode metadata cache and optional pre-play preparation.

No torrent additions, unlocking, accounts or persistent URLs. Network is used
only for a few already-direct candidates or the selected resolved video.
"""
import json
import os
import re
import sqlite3
import time
import xbmcvfs
from resources.lib.playback.chapter_facts import fingerprint
from resources.lib.playback import media_probe,timing_rules,timing_service
from resources.lib.playback.episode_policy import EpisodeError

class Cache:
    def __init__(self,addon):self.path=os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')),'media_metadata.sqlite')
    def connect(self):
        os.makedirs(os.path.dirname(self.path),exist_ok=True)
        db=sqlite3.connect(self.path,timeout=.2)
        try:
            db.execute('PRAGMA cache_size=-128')
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):raise ValueError('newer metadata cache')
            db.execute('CREATE TABLE IF NOT EXISTS metadata (identity TEXT PRIMARY KEY,value TEXT,expires REAL,updated REAL)')
            db.execute('PRAGMA user_version=1');return db
        except Exception:db.close();raise
    def get(self,identity):
        return self.get_many([identity]).get(identity)
    def get_many(self,identities):
        identities=[key for key in identities if isinstance(key,str) and re.fullmatch('[0-9a-f]{64}',key)][:500]
        if not identities:return {}
        db=None
        try:
            db=self.connect();result={}
            query='SELECT identity,value FROM metadata WHERE expires>? AND identity IN ('+','.join('?' for _ in identities)+')'
            for identity,raw in db.execute(query,[time.time()]+identities):
                try:
                    value=json.loads(raw)
                    if not isinstance(value,dict) or value.get('status') not in ('ready','unavailable'):continue
                    if value['status']=='ready':
                        duration=timing_rules.number(value.get('duration'),1);marks=value.get('chapters')
                        if not duration or not isinstance(marks,list) or len(marks)>200:continue
                        from resources.lib.playback.episode_policy import chapter_marks
                        if len(chapter_marks(marks,duration))!=len(marks):continue
                    result[identity]=value
                except (ValueError,TypeError,EpisodeError):continue
            return result
        except (OSError,sqlite3.Error,ValueError,TypeError):return {}
        finally:
            if db:db.close()
    def save(self,identity,value):
        if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity):return
        if value.get('status')=='ready':
            clean={k:value[k] for k in ('status','format','duration','chapters')}
            ttl=90*86400
        else:clean={'status':'unavailable'};ttl=600
        encoded=json.dumps(clean,allow_nan=False)
        if len(encoded)>65536:return
        db=None
        try:
            db=self.connect();now=time.time()
            db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?,?,?)',(identity,encoded,now+ttl,now))
            db.execute('DELETE FROM metadata WHERE identity IN (SELECT identity FROM metadata ORDER BY updated DESC,identity LIMIT -1 OFFSET 1000)');db.commit()
        except (OSError,sqlite3.Error,ValueError):pass
        finally:
            if db:db.close()

def active(addon):return addon.getSetting('episode_metadata_probe')!='false'

def decorate(addon,rows):
    if not active(addon):return rows
    keys=[fingerprint(row) for row in rows if timing_rules.identity((row.get('extra') or {}).get('item'))]
    cached=Cache(addon).get_many(keys);result=[]
    for row in rows:
        extra=dict(row.get('extra') or {});value=cached.get(fingerprint(row))
        if value and value['status']=='ready':
            extra.update(file_duration_seconds=value['duration'],file_duration_origin='header')
            if value['chapters']:extra['has_chapters']=True
        result.append(dict(row,extra=extra))
    return result

def prepare(addon,source,url,seconds=4,cancel=lambda:False):
    if not active(addon) or not timing_rules.identity((source.get('extra') or {}).get('item')):return None
    identity=fingerprint(source)
    if not identity:return None
    cache=Cache(addon);value=cache.get(identity)
    if value is None:
        value=media_probe.probe(url,seconds,cancel)
        if cancel():return None
        cache.save(identity,value)
    if value['status']=='ready':
        source['extra']=dict(source.get('extra') or {},file_duration_seconds=value['duration'],file_duration_origin='header')
        if value.get('chapters'):source['extra']['has_chapters']=True
        timing_service.enqueue(addon,source['extra']['item'],value['duration'])
    return value

def search_candidates(addon,rows,cancel=lambda:False):
    # Never unlock unselected magnets just to measure them. Cache enrichment
    # applies to all sources; network preflight is limited to three free URLs.
    if not active(addon) or addon.getSetting('device_source_order')!='IntroDB match':return rows
    end=time.monotonic()+5;count=0
    from resources.lib.playback.files import web_url
    for row in rows:
        if count>=3 or time.monotonic()>=end or cancel():break
        if row.get('debrid') or not web_url(row.get('url')):continue
        if not timing_rules.identity((row.get('extra') or {}).get('item')):continue
        if Cache(addon).get(fingerprint(row)) is not None:continue
        count+=1;prepare(addon,row,row['url'],min(1.5,max(.1,end-time.monotonic())),cancel)
    return rows

def chapters(addon,identity,duration):
    if not active(addon):return []
    value=Cache(addon).get(identity)
    # Kodi's actual runtime wins if a host supplied another edit/transcode.
    if value and value['status']=='ready' and abs(value['duration']-duration)<=2:return value['chapters']
    return []

def description(addon,identity):
    if not active(addon):return 'Video metadata preparation: off'
    value=Cache(addon).get(identity)
    if not value:return 'Video metadata: not measured for this release'
    if value['status']!='ready':return 'Video metadata unavailable: unsupported, non-seekable or outside preparation budget. Playback continues.'
    return 'Video metadata: {} · file duration {:.3f}s · {} chapter markers. Generic chapter names do not identify an intro.'.format(value.get('format','container'),value['duration'],len(value['chapters']))
