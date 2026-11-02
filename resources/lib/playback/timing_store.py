"""Bounded device-local cache/jobs/facts; no URLs, credentials or media bytes."""
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
import xbmcvfs
from resources.lib.playback import timing_rules as rules


class TimingError(Exception):pass


class Store:
    def __init__(self,addon):self.path=os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')),'episode_timings.sqlite')
    @contextmanager
    def db(self):
        db=None
        try:
            os.makedirs(os.path.dirname(self.path),exist_ok=True)
            db=sqlite3.connect(self.path,timeout=.3);db.row_factory=sqlite3.Row;db.execute('PRAGMA cache_size=-128')
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise TimingError('Newer timing database; update Flix.')
            db.execute('CREATE TABLE IF NOT EXISTS cache (identity TEXT,provider TEXT,value TEXT,expires REAL,status TEXT,PRIMARY KEY(identity,provider))')
            db.execute('CREATE TABLE IF NOT EXISTS jobs (identity TEXT PRIMARY KEY,item TEXT,duration REAL,created REAL,lease REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS providers (name TEXT PRIMARY KEY,retry REAL,day INTEGER,calls INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS facts (identity TEXT PRIMARY KEY,duration REAL,updated REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS confirmations (identity TEXT,kind TEXT,value TEXT,duration REAL,updated REAL,PRIMARY KEY(identity,kind))')
            db.execute('CREATE TABLE IF NOT EXISTS fetches (identity TEXT,hint INTEGER,updated REAL,PRIMARY KEY(identity,hint))')
            db.execute('PRAGMA user_version=1');yield db;db.commit()
        except (sqlite3.Error,OSError,ValueError):raise TimingError('Episode timing storage unavailable; existing data kept.') from None
        finally:
            if db:db.close()
    def queue(self,item,duration=0):
        item=rules.clean_identity(item)
        if not item:return False
        identity=rules.key(item);duration=rules.number(duration) or 0;now=time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            cached=db.execute('SELECT count(*) FROM cache WHERE identity=? AND expires>?',(identity,now)).fetchone()[0]
            # Fresh responses are reused. A new actual duration may enqueue a
            # one-off refresh when it differs materially from the cached groups.
            if cached>=2:
                if not duration:return False
                rows=[]
                for row in db.execute('SELECT value FROM cache WHERE identity=? AND expires>?',(identity,now)):
                    rows.extend(json.loads(row[0]))
                if any(rules.number(row.get('runtime')) and abs(row['runtime']-duration)<=5 for row in rows):return False
                previous=db.execute('SELECT updated FROM fetches WHERE identity=? AND hint=?',(identity,round(duration),)).fetchone()
                if previous and previous[0]>now-86400:return False
            if db.execute('SELECT 1 FROM jobs WHERE identity=?',(identity,)).fetchone():return False
            if db.execute('SELECT count(*) FROM jobs').fetchone()[0]>=50:return False
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,0)',(identity,json.dumps(item),duration,now))
        return True
    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');now=time.time()
            row=db.execute('SELECT * FROM jobs WHERE lease<? ORDER BY created LIMIT 1',(now,)).fetchone()
            if not row:return None
            db.execute('UPDATE jobs SET lease=? WHERE identity=?',(now+90,row['identity']))
            db.execute('INSERT OR REPLACE INTO fetches VALUES(?,?,?)',(row['identity'],round(row['duration']),now))
            db.execute('DELETE FROM fetches WHERE rowid IN (SELECT rowid FROM fetches ORDER BY updated DESC LIMIT -1 OFFSET 1000)')
            result=dict(row);result['lease']=now+90;return result
    def finish(self,job):
        with self.db() as db:db.execute('DELETE FROM jobs WHERE identity=? AND lease=?',(job['identity'],job['lease']))
    def data(self,item):
        identity=rules.key(item);rows=[];status=[]
        if not identity:return rows,status
        with self.db() as db:
            for row in db.execute('SELECT * FROM cache WHERE identity=?',(identity,)):
                fresh=row['expires']>time.time()
                status.append(row['provider']+': '+(row['status'] if fresh else 'expired'))
                if fresh:
                    value=json.loads(row['value'])
                    if not isinstance(value,list) or not all(isinstance(entry,dict) for entry in value):raise TimingError('Invalid timing cache; existing data kept.')
                    rows.extend(value)
            if db.execute('SELECT 1 FROM jobs WHERE identity=?',(identity,)).fetchone():status.append('Background lookup pending')
        return rows,status
    def save(self,item,provider,rows,status='Ready',ttl=7*86400):
        if provider not in ('TheIntroDB','IntroDB'):raise TimingError('Unknown timing provider.')
        encoded=json.dumps(rows,allow_nan=False)
        if len(encoded)>65536:raise TimingError('Timing response is too large.')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?)',(rules.key(item),provider,encoded,time.time()+ttl,status))
            db.execute('DELETE FROM cache WHERE rowid IN (SELECT rowid FROM cache ORDER BY expires DESC LIMIT -1 OFFSET 400)')
    def reserve(self,provider):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');now=time.time();day=int(now//86400)
            row=db.execute('SELECT * FROM providers WHERE name=?',(provider,)).fetchone()
            count=row['calls'] if row and row['day']==day else 0
            if row and row['retry']>now or count>=300:return False
            db.execute('INSERT OR REPLACE INTO providers VALUES(?,?,?,?)',(provider,0,day,count+1));return True
    def backoff(self,provider,seconds):
        with self.db() as db:db.execute('UPDATE providers SET retry=? WHERE name=?',(time.time()+max(60,min(seconds,86400)),provider))
    def observe(self,identity,duration):
        duration=rules.number(duration,60)
        if not duration or not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity):return
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO facts VALUES(?,?,?)',(identity,duration,time.time()))
            db.execute('DELETE FROM facts WHERE identity IN (SELECT identity FROM facts ORDER BY updated DESC LIMIT -1 OFFSET 1000)')
    def durations(self):
        with self.db() as db:return dict(db.execute('SELECT identity,duration FROM facts WHERE updated>?',(time.time()-90*86400,)))
    def confirm(self,identity,row,duration):
        bounds=rules.fallback_interval(row,duration)
        if not bounds or not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity):raise TimingError('This suggestion does not fit the playing file.')
        value=dict(kind=row['kind'],start=bounds[0],end=bounds[1],provider='Your confirmed timing')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO confirmations VALUES(?,?,?,?,?)',(identity,row['kind'],json.dumps(value),duration,time.time()))
            db.execute('DELETE FROM confirmations WHERE rowid IN (SELECT rowid FROM confirmations ORDER BY updated DESC LIMIT -1 OFFSET 1000)')
    def confirmed(self,identity,duration,kind):
        with self.db() as db:row=db.execute('SELECT * FROM confirmations WHERE identity=? AND kind=?',(identity,kind)).fetchone()
        if row and abs(row['duration']-duration)<=5:
            result=json.loads(row['value']);bounds=rules.interval(result,duration)
            if bounds:return dict(result,range=bounds)
        return None
    def clear_confirmation(self,identity):
        with self.db() as db:db.execute('DELETE FROM confirmations WHERE identity=?',(identity,))
