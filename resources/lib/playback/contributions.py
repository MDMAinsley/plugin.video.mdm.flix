"""Consented, bounded timing outbox. Network work runs outside playback/UI ticks."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request

import xbmcgui
import xbmcvfs

from resources.lib.playback.timing_store import TimingError

BASE = 'https://mdmskip.mdmainsley.co.uk'
HEX = re.compile(r'[0-9a-f]{64}')
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
CONSENT = 'timing_share_consent_v1'
NOTICE = ('Share intro/outro timings and ratings for the public MDM Skip catalogue on GitHub? '
          'We send episode numbers, runtime, timing ranges and audio fingerprint digests when available. '
          'No name, device details, stream links or raw audio are included. A random contributor key is '
          'kept to prevent repeat votes; the service and hosting provider can see connection information. '
          'Submissions wait for verification. You can turn sharing off and delete unsent entries in Timing sharing. '
          'Choose No to keep timings on this device.')


def enabled(addon):
    return addon.getSetting(CONSENT) == 'true'


def consent(addon, configure=False):
    previous = addon.getSetting(CONSENT)
    if not configure and previous in ('true', 'false'):
        return previous == 'true'
    accepted = xbmcgui.Dialog().yesno('Share timings with MDM Skip?', NOTICE)
    addon.setSetting(CONSENT, 'true' if accepted else 'false')
    return accepted


def evidence(addon, context):
    """Never transmit local file fingerprints or hashes derived from stream URLs."""
    path = Path(xbmcvfs.translatePath(addon.getAddonInfo('profile'))) / 'shared_cut_evidence.json'
    try:
        with path.open(encoding='utf8') as stream:
            raw = stream.read(2049)
        if len(raw) > 2048:
            return []
        row = json.loads(raw)
        item = context['item']
        if (row.get('schema') != 1 or row.get('file_id') != context['audio_file']
                or any(row.get(k) != item[k] for k in ('tmdb_id', 'season', 'episode'))
                or type(row.get('duration')) not in (int, float)
                or not math.isfinite(row['duration']) or abs(row['duration']-context['duration']) > 2):
            return []
        from resources.lib.playback.shared_catalogue import anchors
        return [list(a) for a in sorted(anchors(row.get('anchors')))]
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return []


def payload(addon, context, row, action):
    from resources.lib.playback.timing_rules import interval
    bounds = interval(row, context['duration'])
    episode = [context['item'][k] for k in ('tmdb_id', 'season', 'episode')]
    if (not bounds or action not in ('good', 'bad', 'correction')
            or any(type(v) is not int for v in episode)
            or not 1 <= episode[0] <= 100000000 or not 0 <= episode[1] <= 1000
            or not 1 <= episode[2] <= 10000 or row.get('kind') not in ('intro', 'outro')):
        raise TimingError('This timing cannot be shared. Its local copy is kept.')
    body = dict(episode=episode, duration=float(context['duration']),
                anchors=evidence(addon, context), marker=row['kind'], start=bounds[0], end=bounds[1],
                origin='manual', assessment=action)
    marker, revision = row.get('marker_id'), row.get('revision')
    if isinstance(marker, str) and HEX.fullmatch(marker) and type(revision) is int and revision > 0:
        body['reference'] = dict(marker=marker, revision=revision)
    return body


class Outbox:
    def __init__(self, addon):
        self.path = os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')), 'timing_outbox.sqlite')

    @contextmanager
    def db(self):
        database = None
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            database = sqlite3.connect(self.path, timeout=.5)
            version = database.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise TimingError('This timing outbox needs a newer MDM Flix.')
            database.execute('PRAGMA cache_size=-64')
            database.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, version TEXT NOT NULL, body TEXT NOT NULL,
                    state TEXT NOT NULL, due REAL NOT NULL, attempts INTEGER NOT NULL,
                    receipt TEXT, detail TEXT NOT NULL, updated REAL NOT NULL
                );
                PRAGMA user_version=1;
            ''')
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            with database:
                yield database
        except (OSError, sqlite3.Error) as error:
            raise TimingError('Timing sharing storage is unavailable. Local timings are kept.') from error
        finally:
            if database:
                database.close()

    def queue(self, key, body):
        encoded = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(encoded) > 4096 or not isinstance(key, str) or not HEX.fullmatch(key):
            raise TimingError('This contribution cannot be queued.')
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT body FROM jobs WHERE id=?', (key,)).fetchone()
            if prior and prior[0] == encoded:
                return
            if not prior and db.execute("SELECT count(*) FROM jobs WHERE state!='received'").fetchone()[0] >= 200:
                raise TimingError('The sharing queue is full. Open Timing sharing to retry or clear unsent entries.')
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',
                       (key, secrets.token_hex(16), encoded, 'queued', now, 0, None, '', now))
            db.execute("DELETE FROM jobs WHERE id IN (SELECT id FROM jobs WHERE state='received' ORDER BY updated DESC LIMIT -1 OFFSET 500)")

    def claim(self):
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND due<=? ORDER BY updated LIMIT 1", (now,)).fetchone()
            if row:
                db.execute('UPDATE jobs SET due=? WHERE id=? AND version=?', (now+60, row['id'], row['version']))
                return dict(row)

    def finish(self, job, receipt=None, detail='Retrying later', permanent=False):
        attempts = job['attempts'] + 1
        with self.db() as db:
            cursor = db.execute('UPDATE jobs SET state=?,due=?,attempts=?,receipt=?,detail=? WHERE id=? AND version=?',
                       ('received' if receipt else 'needs_attention' if permanent else 'queued',
                        time.time()+min(3600, 30*2**min(attempts, 7)), attempts, receipt, detail,
                        job['id'], job['version']))
            return cursor.rowcount == 1

    def token(self, value=None):
        with self.db() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('token', value))
            row = db.execute('SELECT value FROM settings WHERE key=?', ('token',)).fetchone()
            return row[0] if row else ''

    def summary(self):
        with self.db() as db:
            counts = dict(db.execute('SELECT state,count(*) FROM jobs GROUP BY state').fetchall())
            row = db.execute("SELECT detail FROM jobs WHERE detail!='' ORDER BY updated DESC LIMIT 1").fetchone()
            return counts, row[0] if row else ''

    def retry(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET state='queued',due=0 WHERE state!='received'")

    def clear_unsent(self):
        with self.db() as db:
            db.execute("DELETE FROM jobs WHERE state!='received'")


class SendError(Exception):
    def __init__(self, code, permanent=False):
        self.code, self.permanent = code, permanent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SendError('Unexpected service redirect')


def post(path, body, token=''):
    if path not in ('/v1/contributors', '/v1/proposals'):
        raise SendError('Invalid submission route', True)
    headers = {'Content-Type':'application/json', 'User-Agent':'MDM-Flix-Timings/1'}
    if token:
        headers['Authorization'] = 'Bearer '+token
    request = urllib.request.Request(BASE+path, json.dumps(body, allow_nan=False).encode(), headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=5) as response:
            status, raw = response.status, response.read(4097)
        if len(raw) > 4096:
            raise SendError('Invalid service response')
        return status, json.loads(raw)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 401:
            raise SendError('Contributor key rejected', True)
        raise SendError('Service request rejected' if error.code in (400,404,413,415) else 'Service unavailable',
                        error.code in (400,404,413,415))
    except (OSError, ValueError) as error:
        raise SendError('Offline or service unavailable') from error


def deliver(addon, transport=post):
    if not enabled(addon):
        return False
    store = Outbox(addon)
    job = store.claim()
    if not job:
        return False
    try:
        token = store.token()
        if not token:
            if not enabled(addon):
                return False
            status, result = transport('/v1/contributors', dict(consent=True))
            if not isinstance(result, dict):
                raise SendError('Invalid contributor acknowledgement')
            token = result.get('token')
            if status != 201 or not isinstance(token, str) or not TOKEN.fullmatch(token):
                raise SendError('Invalid contributor acknowledgement')
            store.token(token)
        if not enabled(addon):
            return False
        status, result = transport('/v1/proposals', dict(json.loads(job['body']), operation=job['version']), token)
        if not isinstance(result, dict):
            raise SendError('Invalid submission acknowledgement')
        receipt = result.get('receipt')
        state = result.get('state')
        if (status != 202 or not isinstance(receipt, str) or not HEX.fullmatch(receipt)
                or state not in ('pending_review', 'pending_cut_verification') or result.get('published') is not False):
            raise SendError('Invalid submission acknowledgement')
        detail = 'Received; awaiting cut verification' if state == 'pending_cut_verification' else 'Received; pending review'
        if result.get('counted_vote') is True:
            detail = 'Anonymous rating recorded' + ('; eligible for community totals' if result.get('eligible_for_promotion') is True else '; eligibility pending')
        if store.finish(job, receipt, detail):
            xbmcgui.Dialog().notification('MDM Skip', 'Contribution received for review.')
        return True
    except SendError as error:
        store.finish(job, detail=error.code, permanent=error.permanent)
        return False


def offer(addon, context, row, action, key):
    if not consent(addon):
        return 'Saved on this device.'
    Outbox(addon).queue(key, payload(addon, context, row, action))
    return 'Saved locally; queued for sharing.'


def manage(addon):
    try:
        store = Outbox(addon)
        counts, detail = store.summary()
        labels = ['Sharing: '+('on' if enabled(addon) else 'off')+' · change consent',
                  'Status: {} queued, {} received, {} need attention'.format(counts.get('queued',0),counts.get('received',0),counts.get('needs_attention',0)),
                  'Retry unsent contributions', 'Delete unsent contributions', 'Back']
        choice = xbmcgui.Dialog().select('Timing sharing', labels)
        if choice == 0:
            consent(addon, configure=True)
        elif choice == 1:
            xbmcgui.Dialog().ok('Timing sharing', (detail or 'No contributions yet.')+'\nReceived contributions are held for verification and review. They are not automatically published. Ratings count only after matching a verified cut and timing revision; anonymous eligibility is checked separately. Turning sharing off stops future uploads; it does not erase entries already received by the service.')
        elif choice == 2:
            store.retry()
            xbmcgui.Dialog().notification('Timing sharing', 'Unsent contributions will retry while sharing is on.')
        elif choice == 3 and xbmcgui.Dialog().yesno('Delete unsent contributions?', 'Local saved timings stay available. An upload already in progress may finish. Entries already received by the service are unaffected.'):
            store.clear_unsent()
    except TimingError as error:
        xbmcgui.Dialog().ok('Timing sharing', str(error))


def start(addon, monitor):
    def run():
        while not monitor.waitForAbort(15):
            try:
                deliver(addon)
            except (TimingError, ValueError, TypeError, KeyError, RuntimeError):
                pass
    thread = threading.Thread(target=run, name='MDM-TimingSharing', daemon=True)
    thread.start()
    return thread
