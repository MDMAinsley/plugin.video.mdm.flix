"""Device-local progress by catalogue identity; no stream URL or account storage."""
import json
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
import xbmcvfs

MAX_RECORDS=1000

class ProgressError(Exception):
    pass

def integer(value, minimum=0):
    if type(value) is bool or not re.fullmatch(r'[0-9]{1,10}',str(value)) or not minimum<=int(value)<2147483647:
        raise ProgressError('This title has no valid tracking identity.')
    return int(value)

def clean(item):
    if not isinstance(item,dict) or item.get('media_type') not in ('movie','episode'):
        raise ProgressError('Only films and individual episodes have playback progress.')
    result={'media_type':item['media_type'],'tmdb_id':integer(item.get('tmdb_id'),1)}
    if result['media_type']=='episode':
        result.update(season=integer(item.get('season')),episode=integer(item.get('episode'),1))
    for key,limit in (('title',200),('tvshowtitle',200),('plot',2000)):
        value=item.get(key);result[key]=value[:limit] if isinstance(value,str) else ''
    if not result['title']:raise ProgressError('This title has no name for Continue Watching.')
    result['year']=integer(item['year'],1) if item.get('year') else 0
    art=item.get('artwork');art=art if isinstance(art,dict) else {}
    result['artwork']={}
    for key in ('poster','fanart','thumb'):
        value=art.get(key,'')
        result['artwork'][key]=value if isinstance(value,str) and re.fullmatch(r'https://image\.tmdb\.org/t/p/[A-Za-z0-9_-]+/[A-Za-z0-9._-]{1,200}',value) else ''
    return result

def key(item):
    item=clean(item)
    return '{}:{}'.format(item['media_type'],item['tmdb_id'])+(':{}:{}'.format(item['season'],item['episode']) if item['media_type']=='episode' else '')

def seconds(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=86400:
        raise ProgressError('Kodi returned an invalid playback position.')
    return float(value)

class Store:
    def __init__(self,addon):
        profile=xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        if not profile:raise ProgressError('Kodi could not locate the progress profile.')
        self.path=os.path.join(profile,'viewing_progress.sqlite')

    @contextmanager
    def db(self,write=False):
        db=None
        try:
            os.makedirs(os.path.dirname(self.path),exist_ok=True)
            db=sqlite3.connect(self.path,timeout=1);db.row_factory=sqlite3.Row;db.execute('PRAGMA cache_size=-128')
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise ProgressError('Update Flix before opening this newer viewing-progress database.')
            if version==0:
                db.execute('CREATE TABLE IF NOT EXISTS progress(identity TEXT PRIMARY KEY, item TEXT NOT NULL, position REAL NOT NULL, duration REAL NOT NULL, watched INTEGER NOT NULL, updated INTEGER NOT NULL)')
                db.execute('PRAGMA user_version=1');db.commit()
            if write:db.execute('BEGIN IMMEDIATE')
            yield db
            if write:db.commit()
        except (sqlite3.Error,OSError):
            raise ProgressError('Viewing progress could not be read or saved. Check device storage and retry; existing data has been kept.') from None
        finally:
            if db:db.close()

    @staticmethod
    def record(row):
        if not row:return None
        try:
            item=clean(json.loads(row['item']))
            if key(item)!=row['identity']:return None
            return dict(item=item,position=seconds(row['position']),duration=seconds(row['duration']),watched=bool(row['watched']),updated=row['updated'])
        except (ValueError,TypeError,KeyError,ProgressError):return None

    def get(self,item):
        identity=key(item)
        with self.db() as db:return self.record(db.execute('SELECT * FROM progress WHERE identity=?',(identity,)).fetchone())

    def save(self,item,position,duration,watched=False):
        item=clean(item);identity=key(item);position=seconds(position);duration=seconds(duration)
        if type(watched) is not bool:raise ProgressError('Invalid watched state.')
        if duration and position>duration:position=duration
        with self.db(True) as db:
            exists=db.execute('SELECT 1 FROM progress WHERE identity=?',(identity,)).fetchone()
            if not exists and db.execute('SELECT count(*) FROM progress').fetchone()[0]>=MAX_RECORDS:
                raise ProgressError('This device has 1000 viewing records. Remove old records in Viewing History to save new ones.')
            db.execute('INSERT INTO progress VALUES(?,?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET item=excluded.item,position=excluded.position,duration=excluded.duration,watched=excluded.watched,updated=excluded.updated',
                       (identity,json.dumps(item,ensure_ascii=False),0 if watched else position,duration,int(watched),int(time.time())))

    def rows(self,continuing=True):
        with self.db() as db:
            sql='SELECT * FROM progress'+(' WHERE watched=0 AND position>=30' if continuing else '')+' ORDER BY updated DESC,identity LIMIT '+('40' if continuing else '1000')
            return [record for row in db.execute(sql) if (record:=self.record(row)) is not None]

    def remove(self,item):
        with self.db(True) as db:db.execute('DELETE FROM progress WHERE identity=?',(key(item),))
