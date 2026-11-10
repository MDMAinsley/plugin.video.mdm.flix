"""Deliver final local checkpoints and verify them outside Kodi player callbacks."""
import json
from datetime import datetime
from threading import Thread
import time

from .mdblist_account import State
from .mdblist_client import CLIENT_ID, Client, DeviceFlow, MDBError, playback_percentage
from .mdblist_import import object_field, parse_paused
from .mdblist_history import item_state, recent_watched, watched_body
from .playback.progress import MAX_RECORDS, ProgressError, Store, key
from .playback.resume_outbox import MAX_RESUME_PERCENT, Outbox
from .playback.viewing_outbox import Actions

APP_NAME = 'MDM Flix'
VERIFY_DELAY = 10
MAX_WRITES = 3
MAX_FAILURES = 10
REFRESH_INTERVAL = 180
HISTORY_INTERVAL = 1800


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
        store = Store(addon)
        self.outbox = Outbox(store)
        self.actions = Actions(store)
        self.boot = boot
        self.stopping = stopping
        self.client_options = {'transport': transport} if transport else {}
        self.refresh_at = 0
        self.refresh_account = None
        self.history_at = 0
        self.last_request = 0

    def tick(self):
        if self.stopping() or self.addon.getSetting('progress_enabled') == 'false':
            return
        current = self.state.connection()
        now = time.time()
        if not current or not current.get('sync_id') or current.get('sync_retry', 0) > now:
            return
        edit = self.actions.pending(current['sync_id'],self.boot) if current.get('history_sync') else None
        row = None if edit else self.outbox.pending(current['sync_id'], now, self.boot)
        if self.refresh_account != current['sync_id']:
            self.refresh_account = current['sync_id']
            self.refresh_at = 0
            self.history_at = 0
            self.last_request = 0
        requested = current.get('progress_refresh',0)
        if requested > self.last_request:
            self.last_request = requested
            self.refresh_at = min(self.refresh_at,now)
            self.history_at = min(self.history_at,now)
        if not (row or edit) and now < self.refresh_at and (not current.get('history_sync') or now < self.history_at):
            return
        try:
            if current['expires'] <= now + 30:
                flow = DeviceFlow(CLIENT_ID, **self.client_options)
                current = self.state.refresh(current, flow.refresh(current['refresh_token']))
            client = Client(token=current['access_token'], **self.client_options)
            if edit:
                self.reconcile_edit(current,edit,client)
            elif row:
                self.reconcile(current, row, client)
            elif now >= self.refresh_at:
                self.read_playback(current, client)
            else:
                self.history_at = now + HISTORY_INTERVAL
                watched, complete = recent_watched(client)
                if not complete:
                    seen = {key(item) for item,_ in watched}
                    watched.extend(row for row in self.state.watched_snapshot(current['sync_id']) if key(row[0]) not in seen)
                self.state.save_watched(current['sync_id'],sorted(watched,key=lambda row:row[1],reverse=True)[:1500],
                                        complete=complete)
        except MDBError as error:
            if edit and error.code != 'connection_changed':
                self.retry_edit(current,edit,error)
            elif row and error.code != 'connection_changed':
                self.retry(current, row, error)
            else:
                self.refresh_at = now + max(REFRESH_INTERVAL,error.retry_after)
                if error.code == 'rate_limited':
                    self.state.sync_status(current,'MDBList asked Flix to wait before syncing.',self.refresh_at)

    def read_playback(self, current, client):
        values = client.playback()
        self.refresh_at = time.time() + REFRESH_INTERVAL
        try:
            records = parse_paused(values)
            present = {remote_key(row) if isinstance(row,dict) else None for row in values}
            # A malformed row may be a previous title with incomplete metadata.
            self.state.save_playback(current['sync_id'],records,present if None not in present else None)
        except MDBError:
            # Keep the previous cache if the new response cannot be stored.
            pass
        return values

    def finish(self, current, row, status):
        if self.outbox.finish(row):
            self.state.sync_status(current, status)

    def edit_identifier(self, item):
        if item['media_type'] == 'movie':
            return item['tmdb_id']
        if item.get('episode_tmdb_id'):
            return item['episode_tmdb_id']
        # Existing viewing rows predate the dedicated episode ID.
        from .bootstrap import _load_core
        from .catalogue.tmdb import CatalogueError, TMDB
        try:
            data = TMDB(self.addon,_load_core()).request('tv/{}/season/{}/episode/{}'.format(
                item['tmdb_id'],item['season'],item['episode']),ttl=3600)
            return data['id']
        except CatalogueError:
            raise MDBError('episode_identity_unavailable') from None

    def finish_edit(self, current, row, message):
        if self.actions.finish(row):
            self.state.sync_status(current,message)

    def reconcile_edit(self, current, row, client):
        item = json.loads(row['item'])
        identifier = self.edit_identifier(item)
        changed = item_state(client,item,identifier)
        pause = remote_position(self.read_playback(current,client),row['identity'])
        self.state.update_watched(current['sync_id'],item,changed)
        recorded = int(row['recorded'])
        if changed > recorded or (pause and pause['updated_at_ts'] >= recorded):
            self.finish_edit(current,row,'Kept newer viewing activity on MDBList.')
            return
        kind = row['kind']
        if kind == 'watched' and changed < recorded:
            path, body = '/sync/watched', watched_body(item,identifier,recorded)
        elif kind in ('unwatched','clear') and changed:
            path, body = '/sync/watched/remove', watched_body(item,identifier)
        elif kind in ('watched','clear') and pause:
            path, body = '/scrobble/clear', target(item)
        else:
            self.finish_edit(current,row,'Viewing change verified on MDBList.')
            return
        if row['writes'] >= 4:
            self.finish_edit(current,row,'Could not verify the viewing change on MDBList.')
            return
        account = self.state.connection()
        if self.stopping() or not account or account['generation'] != current['generation']:
            return
        if not self.actions.begin(row):
            return
        result = client.call('POST',path,body)
        unmatched = result.get('not_found') if isinstance(result,dict) else None
        if isinstance(unmatched,dict):
            unmatched = any(unmatched.values())
        if not isinstance(result,dict) or result.get('errors') or unmatched:
            raise MDBError('request_rejected')
        if self.actions.defer(row,VERIFY_DELAY):
            self.state.sync_status(current,'Uploaded viewing change. Checking MDBList shortly.')

    def retry_edit(self, current, row, error):
        failures = row['failures'] + 1
        if failures >= MAX_FAILURES or error.code in ('request_rejected','title_not_found'):
            self.finish_edit(current,row,'MDBList could not apply this viewing change. The local change is saved.')
            return
        delay = max(15,error.retry_after) if error.code == 'rate_limited' else min(3600,15*2**(failures-1))
        if error.code in ('invalid_grant','unauthorised','invalid_client'):
            delay = 86400
        if self.actions.defer(row,delay,failures):
            self.state.sync_status(current,'MDBList viewing change is waiting for a retry.',time.time()+delay)

    def reconcile(self, current, row, client):
        item = json.loads(row['item'])
        remote = remote_position(self.read_playback(current,client), row['identity'])
        local_duration = row['duration']
        catalogue_duration = item.get('duration_seconds',0)
        duration = readback_duration(remote, catalogue_duration or local_duration)
        difference = abs(duration - local_duration)
        own_upload = bool(remote and matches_upload(row,remote))
        known_runtime = catalogue_duration and abs(duration-catalogue_duration)<=60
        can_translate = difference <= max(120,local_duration*.10) and (own_upload or known_runtime)
        if difference > max(60,local_duration*.05) and not can_translate:
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
            if remote['updated_at_ts'] >= int(row['sampled']) and not own_upload:
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
