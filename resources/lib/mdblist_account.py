"""Device connection state in the Flix profile, separate from the local library."""
import json
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import time
import uuid

import xbmcvfs

from .mdblist_client import MDBError


class State:
    def __init__(self, addon):
        profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        if not profile:
            raise MDBError('storage_unavailable')
        self.path = Path(profile) / 'mdblist_account.sqlite'

    @contextmanager
    def db(self, write=False):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=1)) as database, database:
                database.execute('PRAGMA secure_delete=ON')
                database.execute('CREATE TABLE IF NOT EXISTS connection (slot INTEGER PRIMARY KEY CHECK(slot=1), value TEXT NOT NULL)')
                if write:
                    database.execute('BEGIN IMMEDIATE')
                yield database
        except (OSError, ValueError, sqlite3.Error):
            raise MDBError('storage_unavailable') from None

    @staticmethod
    def current(database):
        row = database.execute('SELECT value FROM connection WHERE slot=1').fetchone()
        return json.loads(row[0]) if row else None

    def connection(self):
        if not self.path.is_file():
            return None
        with self.db() as database:
            return self.current(database)

    def replace(self, value, generation=None):
        with self.db(write=True) as database:
            if (self.current(database) or {}).get('generation') != generation:
                return False
            if value is None:
                database.execute('DELETE FROM connection WHERE slot=1')
            else:
                database.execute('INSERT OR REPLACE INTO connection VALUES(1,?)', (json.dumps(value),))
        return True

    @contextmanager
    def guard(self, connection):
        with self.db(write=True) as database:
            if (self.current(database) or {}).get('generation') != connection['generation']:
                raise MDBError('connection_changed')
            yield

    def connect(self, account, tokens, *, sync=False):
        row = dict(account, generation=uuid.uuid4().hex, access_token=tokens['access_token'],
                   refresh_token=tokens['refresh_token'], expires=time.time()+tokens['expires_in'],
                   write_access=tokens.get('scope') == 'write')
        if sync:
            if not row['write_access']:
                raise MDBError('write_permission')
            row.update(sync_id=uuid.uuid4().hex, sync_retry=0, sync_status='', history_sync=True)
        return self.replace(row)

    def enable_sync(self, previous, account=None, tokens=None):
        row = dict(previous)
        if tokens is not None:
            if account['id'] != previous['id']:
                raise MDBError('different_account')
            row.update(name=account['name'], access_token=tokens['access_token'], refresh_token=tokens['refresh_token'],
                       expires=time.time()+tokens['expires_in'], write_access=tokens.get('scope') == 'write')
        if not row.get('write_access'):
            raise MDBError('write_permission')
        row.update(generation=uuid.uuid4().hex, sync_id=uuid.uuid4().hex, sync_retry=0, sync_status='', history_sync=True)
        return self.replace(row, previous['generation'])

    def disable_sync(self, previous):
        row = dict(previous, generation=uuid.uuid4().hex)
        # Older connections only had a sync ID after MDBList granted write access.
        row.setdefault('write_access', bool(previous.get('sync_id')))
        for field in ('sync_id', 'sync_retry', 'sync_status', 'history_sync', 'progress_refresh'):
            row.pop(field, None)
        return self.replace(row, previous['generation'])

    def enable_history(self, previous):
        return self.replace(dict(previous,history_sync=True,generation=uuid.uuid4().hex),previous['generation'])

    def request_progress_refresh(self, previous):
        with self.db(write=True) as database:
            row = self.current(database)
            if not row or not row.get('sync_id') or row['sync_id'] != previous.get('sync_id'):
                return False
            now = time.time()
            if now - row.get('progress_refresh',0) >= 15:
                row['progress_refresh'] = now
                database.execute('UPDATE connection SET value=? WHERE slot=1',(json.dumps(row),))
            return True

    def sync_status(self, connection, message, retry=0):
        with self.db(write=True) as database:
            row = self.current(database)
            if row and row.get('sync_id') == connection['sync_id']:
                row.update(sync_status=message, sync_retry=retry)
                database.execute('UPDATE connection SET value=? WHERE slot=1', (json.dumps(row),))

    def save_playback(self, sync_id, records, present=None):
        with self.db(write=True) as database:
            row = self.current(database)
            if not row or row.get('sync_id') != sync_id:
                return
            database.execute('CREATE TABLE IF NOT EXISTS playback_cache ('
                             'slot INTEGER PRIMARY KEY CHECK(slot=1), sync_id TEXT, saved REAL, data TEXT)')
            previous = database.execute('SELECT data FROM playback_cache WHERE slot=1 AND sync_id=?', (sync_id,)).fetchone()
            data = json.dumps(records,ensure_ascii=False)
            removals_changed = present is not None and self.record_removals(database,'playback',sync_id,present)
            database.execute('INSERT OR REPLACE INTO playback_cache VALUES(1,?,?,?)',
                             (sync_id,time.time(),data))
            return not previous or previous[0] != data or removals_changed

    def save_watched(self, sync_id, records, *, complete=False):
        from .playback.progress import key
        with self.db(write=True) as database:
            row = self.current(database)
            if not row or row.get('sync_id') != sync_id or not row.get('history_sync'):
                return
            database.execute('CREATE TABLE IF NOT EXISTS watched_cache (slot INTEGER PRIMARY KEY CHECK(slot=1), '
                             'sync_id TEXT, saved REAL, data TEXT)')
            previous = database.execute('SELECT data FROM watched_cache WHERE slot=1 AND sync_id=?', (sync_id,)).fetchone()
            data = json.dumps(records,ensure_ascii=False)
            removals_changed = complete and self.record_removals(database,'watched',sync_id,{key(item) for item,_ in records})
            database.execute('INSERT OR REPLACE INTO watched_cache VALUES(1,?,?,?)',
                             (sync_id,time.time(),data))
            return not previous or previous[0] != data or removals_changed

    @staticmethod
    def record_removals(database, kind, sync_id, present):
        from .playback.progress import key
        previous = database.execute('SELECT data FROM '+kind+'_cache WHERE slot=1 AND sync_id=?',(sync_id,)).fetchone()
        database.execute('CREATE TABLE IF NOT EXISTS viewing_removals (kind TEXT PRIMARY KEY, sync_id TEXT, data TEXT)')
        old = database.execute('SELECT data FROM viewing_removals WHERE kind=? AND sync_id=?',(kind,sync_id)).fetchone()
        now = int(time.time())
        records = {identity:value for identity,value in (json.loads(old[0]) if old else {}).items()
                   if identity not in present and value[0] >= now-7*86400}
        for record in json.loads(previous[0]) if previous else ():
            identity = key(record[0])
            if identity not in present:
                records[identity] = [now,record[1:]]
        newest = sorted(records.items(),key=lambda row:row[1][0],reverse=True)[:1500]
        data = json.dumps(dict(newest))
        database.execute('INSERT OR REPLACE INTO viewing_removals VALUES(?,?,?)',(kind,sync_id,data))
        return (old[0] if old else '{}') != data

    def viewing_removals(self, sync_id):
        with self.db() as database:
            if not database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='viewing_removals'").fetchone():
                return {}
            cutoff = time.time()-7*86400
            return {kind:{identity:value for identity,value in json.loads(data).items() if value[0]>=cutoff}
                    for kind,data in database.execute('SELECT kind,data FROM viewing_removals WHERE sync_id=?',(sync_id,))}

    def watched_snapshot(self, sync_id):
        if not sync_id or not self.path.is_file():
            return []
        with self.db() as database:
            if not database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='watched_cache'").fetchone():
                return []
            cached=database.execute('SELECT data FROM watched_cache WHERE slot=1 AND sync_id=? AND saved>=?',
                                    (sync_id,time.time()-7*86400)).fetchone()
            return json.loads(cached[0]) if cached else []

    def update_watched(self, sync_id, item, timestamp):
        from .playback.progress import key
        with self.db(write=True) as database:
            row = self.current(database)
            if not row or row.get('sync_id') != sync_id or not row.get('history_sync'):
                return
            database.execute('CREATE TABLE IF NOT EXISTS watched_cache (slot INTEGER PRIMARY KEY CHECK(slot=1), '
                             'sync_id TEXT, saved REAL, data TEXT)')
            current = database.execute('SELECT saved,data FROM watched_cache WHERE slot=1 AND sync_id=?',
                                       (sync_id,)).fetchone()
            saved, records = (current[0],json.loads(current[1])) if current else (time.time(),[])
            identity = key(item)
            records = [record for record in records if key(record[0]) != identity]
            if timestamp:
                records.insert(0,[item,timestamp])
            database.execute('INSERT OR REPLACE INTO watched_cache VALUES(1,?,?,?)',
                             (sync_id,saved,json.dumps(records,ensure_ascii=False)))

    def playback_snapshot(self):
        if not self.path.is_file():
            return None, []
        with self.db() as database:
            row = self.current(database)
            sync_id = row.get('sync_id') if row else None
            if not sync_id or not database.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='playback_cache'").fetchone():
                return sync_id, []
            cached = database.execute('SELECT data FROM playback_cache WHERE slot=1 AND sync_id=? AND saved>=?',
                                      (sync_id,time.time()-7*86400)).fetchone()
            return sync_id, json.loads(cached[0]) if cached else []

    def refresh(self, previous, tokens):
        with self.db(write=True) as database:
            row = self.current(database)
            if not row or row['generation'] != previous['generation']:
                raise MDBError('connection_changed')
            row.update(access_token=tokens['access_token'], refresh_token=tokens['refresh_token'],
                       expires=time.time()+tokens['expires_in'], generation=uuid.uuid4().hex)
            if tokens.get('scope'):
                row['write_access'] = tokens['scope'] == 'write'
            database.execute('UPDATE connection SET value=? WHERE slot=1', (json.dumps(row),))
        return row

    def disconnect(self, previous):
        return self.replace(None, previous['generation'])
