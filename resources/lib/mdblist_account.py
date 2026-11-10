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

    def connect(self, account, tokens):
        row = dict(account, generation=uuid.uuid4().hex, access_token=tokens['access_token'],
                   refresh_token=tokens['refresh_token'], expires=time.time()+tokens['expires_in'])
        return self.replace(row)

    def enable_sync(self, previous, account, tokens):
        if account['id'] != previous['id']:
            raise MDBError('different_account')
        if tokens.get('scope') != 'write':
            raise MDBError('write_permission')
        row = dict(previous, name=account['name'], generation=uuid.uuid4().hex, sync_id=uuid.uuid4().hex,
                   access_token=tokens['access_token'], refresh_token=tokens['refresh_token'],
                   expires=time.time()+tokens['expires_in'], sync_retry=0, sync_status='')
        return self.replace(row, previous['generation'])

    def disable_sync(self, previous):
        row = dict(previous, generation=uuid.uuid4().hex)
        for field in ('sync_id', 'sync_retry', 'sync_status'):
            row.pop(field, None)
        return self.replace(row, previous['generation'])

    def sync_status(self, connection, message, retry=0):
        with self.db(write=True) as database:
            row = self.current(database)
            if row and row.get('sync_id') == connection['sync_id']:
                row.update(sync_status=message, sync_retry=retry)
                database.execute('UPDATE connection SET value=? WHERE slot=1', (json.dumps(row),))

    def refresh(self, previous, tokens):
        with self.db(write=True) as database:
            row = self.current(database)
            if not row or row['generation'] != previous['generation']:
                raise MDBError('connection_changed')
            row.update(access_token=tokens['access_token'], refresh_token=tokens['refresh_token'],
                       expires=time.time()+tokens['expires_in'], generation=uuid.uuid4().hex)
            database.execute('UPDATE connection SET value=? WHERE slot=1', (json.dumps(row),))
        return row

    def disconnect(self, previous):
        return self.replace(None, previous['generation'])
