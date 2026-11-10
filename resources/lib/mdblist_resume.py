"""Deliver final local checkpoints and verify them outside Kodi player callbacks."""
import json
from datetime import datetime
from threading import Thread
import time

from .mdblist_account import State
from .mdblist_client import CLIENT_ID, Client, DeviceFlow, MDBError, playback_percentage
from .mdblist_import import object_field
from .playback.progress import MAX_RECORDS, ProgressError, Store, key
from .playback.resume_outbox import MAX_RESUME_PERCENT, Outbox

APP_NAME = 'MDM Flix'
VERIFY_DELAY = 10
MAX_WRITES = 3
MAX_FAILURES = 10


def target(item):
    ids = {'tmdb': item['tmdb_id']}
    if item['media_type'] == 'movie':
        return {'movie': {'ids': ids}}
    return {'show': {'ids': ids, 'season': item['season'], 'episode': item['episode']}}


def remote_key(row):
    media = row.get('type')
    parent = object_field(row, 'movie' if media == 'movie' else 'show')
    episode = object_field(row, 'episode')
    try:
        return key(dict(media_type=media, title=APP_NAME, tmdb_id=object_field(parent, 'ids').get('tmdb'),
                        season=episode.get('season'), episode=episode.get('number')))
    except ProgressError:
        return None


def remote_position(values, identity):
    if not isinstance(values, list) or len(values) > MAX_RECORDS:
        raise MDBError('invalid_response')
    latest = None
    for row in values:
        if not isinstance(row, dict) or remote_key(row) != identity:
            continue
        percentage, updated = playback_percentage(row.get('progress')), row.get('updated_at_ts')
        if percentage is None or type(updated) is not int or updated <= 0:
            raise MDBError('invalid_response')
        if not latest or updated >= latest['updated_at_ts']:
            latest = dict(row, progress=percentage)
    return latest


def readback_duration(remote, local):
    minutes = remote.get('runtime') if remote else None
    if type(minutes) is not int or not 0 < minutes <= 1440:
        return local
    return minutes * 60


def sent_marker(response, requested, started):
    if not isinstance(response, dict) or playback_percentage(response.get('progress')) != requested:
        raise MDBError('invalid_response')
    identifier = response.get('id')
    if type(identifier) is not int or identifier <= 0:
        return None, started
    try:
        paused = datetime.fromisoformat(response['paused_at'].replace('Z', '+00:00'))
        if paused.tzinfo is not None:
            return identifier, int(paused.timestamp())
    except (AttributeError, KeyError, ValueError, OverflowError, OSError):
        pass
    return None, started


def matches_upload(row, remote):
    sent_time = row['sent_time']
    if sent_time is None or remote.get('app_name') != APP_NAME:
        return False
    if row['sent_id'] is not None:
        return row['sent_id'] == remote.get('id') and sent_time == remote['updated_at_ts']
    # The live pause response can omit the session ID and timestamp. Use its
    # echoed progress and the request window to identify the matching readback.
    return row.get('sent_progress') == remote['progress'] and sent_time - 2 <= remote['updated_at_ts'] <= sent_time + 12


class Worker:
    def __init__(self, addon, boot, stopping=lambda: False, transport=None):
        self.addon = addon
        self.state = State(addon)
        self.outbox = Outbox(Store(addon))
        self.boot = boot
        self.stopping = stopping
        self.client_options = {'transport': transport} if transport else {}

    def tick(self):
        if self.stopping() or self.addon.getSetting('progress_enabled') == 'false':
            return
        current = self.state.connection()
        now = time.time()
        if not current or not current.get('sync_id') or current.get('sync_retry', 0) > now:
            return
        row = self.outbox.pending(current['sync_id'], now, self.boot)
        if not row:
            return
        try:
            if current['expires'] <= now + 30:
                flow = DeviceFlow(CLIENT_ID, **self.client_options)
                current = self.state.refresh(current, flow.refresh(current['refresh_token']))
            client = Client(token=current['access_token'], **self.client_options)
            self.reconcile(current, row, client)
        except MDBError as error:
            if error.code != 'connection_changed':
                self.retry(current, row, error)

    def finish(self, current, row, status):
        if self.outbox.finish(row):
            self.state.sync_status(current, status)

    def reconcile(self, current, row, client):
        remote = remote_position(client.playback(), row['identity'])
        duration = readback_duration(remote, row['duration'])
        if abs(duration - row['duration']) > max(60, row['duration'] * .05):
            self.finish(current, row, 'Kept the local position. MDBList has a different runtime for this title.')
            return
        desired = row['position'] / duration * 100
        if desired > MAX_RESUME_PERCENT:
            self.finish(current, row, 'Kept the local position near the end of this title.')
            return
        if remote:
            tolerance = max(1, duration * .00005)
            if abs(remote['progress'] * duration / 100 - row['position']) <= tolerance:
                status = ('Playback position verified on MDBList.' if remote.get('runtime') == duration / 60
                          else 'Playback percentage verified. MDBList did not report a usable runtime.')
                self.finish(current, row, status)
                return
            if remote['updated_at_ts'] >= int(row['sampled']) and not matches_upload(row, remote):
                self.finish(current, row, 'Kept the newer or simultaneous MDBList position.')
                return
        elif row['sent_time'] is not None:
            # An acknowledged position can be removed on another device. Recheck
            # briefly without recreating a possibly deleted remote session.
            if row['failures'] < 2:
                self.outbox.defer(row, time.time() + VERIFY_DELAY, row['failures'] + 1,
                                  row['sent_id'], row['sent_time'])
            else:
                self.finish(current, row, 'MDBList no longer lists the uploaded position. The local position is saved.')
            return
        if row['writes'] >= MAX_WRITES:
            self.finish(current, row, 'Could not verify the position on MDBList. The local position is saved.')
            return
        if self.stopping():
            return
        account = self.state.connection()
        if not account or account['generation'] != current['generation']:
            return
        if not self.outbox.begin_write(row):
            return
        item = json.loads(row['item'])
        requested = round(desired, 2)
        started = int(time.time())
        # MDBList validates a decimal percentage with at most five digits.
        result = client.call('POST', '/scrobble/pause', dict(target(item), progress=requested, app_name=APP_NAME))
        sent_id, sent_time = sent_marker(result, requested, started)
        if self.outbox.defer(row, time.time() + VERIFY_DELAY, sent_id=sent_id, sent_time=sent_time, sent_progress=requested):
            self.state.sync_status(current, 'Uploaded. Checking the position shortly.')

    def retry(self, current, row, error):
        failures = row['failures'] + 1
        if error.code == 'request_rejected':
            self.finish(current, row, 'MDBList rejected the progress request. The local position is saved.')
            return
        if error.code in ('invalid_grant', 'unauthorised', 'invalid_client'):
            self.state.sync_status(current, 'MDBList needs a new sign-in to continue uploading.', time.time() + 86400)
            return
        if failures >= MAX_FAILURES:
            self.finish(current, row, 'MDBList could not verify this stop. The local position is saved.')
            return
        delay = max(15, error.retry_after) if error.code == 'rate_limited' else min(3600, 15 * 2**(failures - 1))
        due = time.time() + delay
        if self.outbox.defer(row, due, failures, row['sent_id'], row['sent_time']):
            self.state.sync_status(current, 'MDBList is temporarily unavailable. Flix will retry.', due)


def start(addon, monitor, boot):
    def run():
        try:
            worker = Worker(addon, boot, monitor.abortRequested)
        except (MDBError, ProgressError):
            return
        while not monitor.abortRequested():
            try:
                worker.tick()
            except (MDBError, ProgressError):
                if monitor.waitForAbort(5):
                    break
            if monitor.waitForAbort(2):
                break

    thread = Thread(target=run, daemon=True, name='MDM-MDBList')
    thread.start()
    return thread
