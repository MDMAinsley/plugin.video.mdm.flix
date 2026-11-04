"""Bounded local timing feedback. No network submission or account collection."""
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sqlite3
import time

import xbmcvfs

from resources.lib.playback import timing_rules as rules
from resources.lib.playback.timing_store import TimingError


class Feedback:
    def __init__(self, addon):
        self.path = os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')), 'timing_feedback.sqlite')

    @contextmanager
    def db(self):
        database = None
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            database = sqlite3.connect(self.path, timeout=.3)
            if database.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
                raise TimingError('This feedback store needs a newer MDM Flix.')
            database.execute('PRAGMA cache_size=-64')
            database.execute('CREATE TABLE IF NOT EXISTS feedback (target TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL)')
            database.execute('PRAGMA user_version=1')
            with database:
                yield database
        except (sqlite3.Error, OSError) as error:
            raise TimingError('Timing feedback could not be saved on this device.') from error
        finally:
            if database:
                database.close()

    def save(self, context, row, action):
        bounds = rules.interval(row, context['duration'])
        item = context['item']
        file_key = context['fingerprint']
        if (not bounds or action not in ('good', 'bad', 'correction')
                or not isinstance(file_key, str) or not re.fullmatch('[0-9a-f]{64}', file_key)):
            raise TimingError('Feedback needs a valid timing for this playing file.')
        episode = [item[name] for name in ('tmdb_id', 'season', 'episode')]
        if any(type(number) is not int for number in episode) or episode[0] < 1 or episode[1] < 0 or episode[2] < 1:
            raise TimingError('Feedback needs the playing episode identity.')
        marker = row.get('marker_id')
        revision = row.get('revision')
        if not isinstance(marker, str) or not re.fullmatch('[0-9a-f]{64}', marker) or type(revision) is not int or revision < 1:
            marker = revision = None
        identity = [episode, file_key, row['kind'], bounds, marker, revision, action == 'correction']
        target = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        value = dict(episode=episode, kind=row['kind'], start=bounds[0], end=bounds[1],
                     marker_id=marker, revision=revision, action=action, status='local')
        with self.db() as database:
            database.execute('INSERT OR REPLACE INTO feedback VALUES(?,?,?)',
                             (target, json.dumps(value), time.time()))
            database.execute('DELETE FROM feedback WHERE target IN (SELECT target FROM feedback ORDER BY updated DESC LIMIT -1 OFFSET 1000)')
        return target

    def count(self):
        with self.db() as database:
            return database.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]

    def clear(self):
        with self.db() as database:
            database.execute('DELETE FROM feedback')
