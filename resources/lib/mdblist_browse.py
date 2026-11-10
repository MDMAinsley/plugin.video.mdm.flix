"""MDBList account, watchlist, imports and resume sync controls."""
import time

import xbmc
import xbmcgui

from .mdblist_account import State
from .mdblist_client import CLIENT_ID, Client, DeviceFlow, MDBError
from . import mdblist_approval, mdblist_import
from .library_store import Library, LibraryError
from .playback.progress import ProgressError, Store

TITLE = 'MDBList'
MESSAGES = {
    'access_denied': 'Sign-in was declined.',
    'expired_token': 'That code expired. Choose Connect MDBList to start again.',
    'invalid_grant': 'This sign-in expired. Disconnect it and connect again.',
    'unauthorised': 'This sign-in expired. Disconnect it and connect again.',
    'rate_limited': 'MDBList asked us to wait. Try again in a moment.',
    'storage_unavailable': 'Kodi could not read or save the MDBList connection.',
    'connection_changed': 'The MDBList connection changed. Open MDBList and try again.',
    'watchlist_too_large': 'This watchlist exceeds the device import limit. You can still browse it.',
    'progress_too_large': 'There are too many paused sessions to import in one operation.',
    'different_account': 'Use the same MDBList account that is connected to Flix.',
    'write_permission': 'MDBList did not grant permission to upload progress.',
}


def safe_label(value, default):
    if not isinstance(value, str):
        return default
    return ''.join(c for c in value[:200] if c.isprintable()).replace('[', '［').replace(']', '］').strip() or default


def connect(state, previous=None, *, sync=False):
    flow = DeviceFlow(CLIENT_ID)
    session = flow.begin('write') if previous or sync else flow.begin()
    monitor = xbmc.Monitor()
    deadline = time.monotonic()+session['expires_in']

    def poll(cancelled):
        interval = session['interval']
        while True:
            next_poll = time.monotonic()+interval
            while time.monotonic() < min(next_poll, deadline):
                if cancelled():
                    return None
            if time.monotonic() >= deadline:
                raise MDBError('expired_token')
            if cancelled():
                return None
            try:
                tokens = flow.poll(session['device_code'])
            except MDBError as error:
                if error.code == 'authorization_pending':
                    continue
                if error.code == 'slow_down':
                    interval += 5
                    continue
                raise
            if cancelled():
                return None
            account = Client(token=tokens['access_token']).account()
            return None if cancelled() else (account, tokens)

    result = mdblist_approval.show(session, monitor, poll)
    if not result or monitor.abortRequested():
        return False
    account, tokens = result
    saved = state.enable_sync(previous, account, tokens) if previous else state.connect(account, tokens,sync=sync)
    if not saved:
        raise MDBError('connection_changed')
    return True


def action(addon, action_name):
    dialog = xbmcgui.Dialog()
    try:
        state = State(addon)
        current = state.connection()
        if action_name == 'mdblist_progress_source':
            active = bool(current and current.get('sync_id'))
            choice = dialog.select('Viewing progress source', ['Local only', 'MDBList'], preselect=int(active))
            if choice == 0 and active:
                action_name = 'mdblist_disable_sync'
            elif choice == 1 and not active:
                action_name = 'mdblist_enable_sync'
            else:
                return
        if action_name == 'mdblist_connect' and not current:
            if connect(state):
                xbmc.executebuiltin('Container.Refresh')
        elif action_name == 'mdblist_disconnect' and current:
            if dialog.yesno(TITLE, 'Disconnect MDBList on this device?', 'Cancel', 'Disconnect'):
                if state.disconnect(current):
                    xbmc.executebuiltin('Container.Refresh')
        elif action_name == 'mdblist_enable_sync' and not (current and current.get('sync_id')):
            message = ('Sync future stop positions and watched changes with MDBList? '
                       'Approve playback access on your phone. Existing viewing history stays on this device.')
            if dialog.yesno(TITLE, message, 'Cancel', 'Continue') and connect(state, current,sync=True):
                dialog.ok(TITLE, 'Progress sync is on. Flix will start syncing from your next playback.')
                xbmc.executebuiltin('Container.Refresh')
        elif action_name == 'mdblist_disable_sync' and current and current.get('sync_id'):
            if state.disable_sync(current):
                xbmc.executebuiltin('Container.Refresh')
        elif action_name == 'mdblist_enable_history' and current and current.get('sync_id') and not current.get('history_sync'):
            if dialog.yesno(TITLE,'Sync future watched and clear changes with MDBList? Existing local history stays on this device.',
                            'Cancel','Enable') and state.enable_history(current):
                xbmc.executebuiltin('Container.Refresh')
        elif action_name == 'mdblist_refresh_progress' and current and current.get('sync_id'):
            if state.request_progress_refresh(current):
                dialog.ok(TITLE,'Refresh requested. Open Continue Watching again in a moment.')
        elif action_name == 'mdblist_sync_status' and current and current.get('sync_id'):
            from .playback.resume_outbox import Outbox
            from .playback.viewing_outbox import Actions
            store = Store(addon)
            count = Outbox(store).count(current['sync_id'])
            changes = len(Actions(store).kinds(current['sync_id']))
            status = current.get('sync_status') or 'Waiting for the next eligible stop position.'
            dialog.ok(TITLE, 'Pending positions: {}\nPending watched or clear changes: {}\n{}'.format(count,changes,status))
        elif action_name in ('mdblist_import_watchlist', 'mdblist_import_progress'):
            if not current:
                dialog.ok(TITLE, 'Connect MDBList before importing.')
                return
            import_local(addon, state, current, dialog, action_name == 'mdblist_import_watchlist')
    except MDBError as error:
        dialog.ok(TITLE, MESSAGES.get(error.code, 'MDBList could not complete this request. Try again.'))
    except (LibraryError, ProgressError) as error:
        dialog.ok(TITLE, str(error))


def connected_client(state, current):
    if current['expires'] <= time.time()+30:
        current = state.refresh(current, DeviceFlow(CLIENT_ID).refresh(current['refresh_token']))
    return Client(token=current['access_token']), current


def import_local(addon, state, current, dialog, watchlist):
    if watchlist:
        store = Library(addon)
        lists = store.lists()
        labels = [safe_label(row['name'], 'Local list') for row in lists]
        selected = dialog.select('Choose a local list', labels)
        if selected < 0:
            return
        label = 'watchlist titles'
        destination = '“{}”'.format(labels[selected])
    else:
        store = Store(addon)
        label = 'paused films or episodes'
        destination = 'Continue Watching'

    progress = xbmcgui.DialogProgress()
    progress.create(TITLE, 'Reading {} from MDBList…'.format(label))
    monitor = xbmc.Monitor()

    def cancelled():
        return progress.iscanceled() or monitor.abortRequested()

    try:
        if cancelled():
            return
        client, current = connected_client(state, current)
        if cancelled():
            return
        rows = mdblist_import.watchlist_titles(client, cancelled) if watchlist else mdblist_import.paused_records(client)
        if cancelled():
            return
    finally:
        progress.close()
    if not rows:
        dialog.ok(TITLE, 'There are no eligible {} to import.'.format(label))
        return
    message = 'Import {} {} into {}? Existing entries on this device will be kept.'.format(
        len(rows), label, destination)
    if not dialog.yesno(TITLE, message, 'Cancel', 'Import'):
        return
    with state.guard(current):
        added = store.import_titles(lists[selected]['id'], rows) if watchlist else store.import_missing(rows)
    dialog.ok(TITLE, 'Added {}. Kept {} already on this device.'.format(added, len(rows)-added))


def show(nav, addon, params):
    try:
        state = State(addon)
        current = state.connection()
        if params.get('action') == 'mdblist_home' or not current:
            if current:
                nav.add_folder('Watchlist · '+safe_label(current['name'], TITLE), 'mdblist_watchlist')
                nav.add_action('Viewing progress source · '+('MDBList' if current.get('sync_id') else 'Local only'),
                               'mdblist_progress_source')
                nav.add_action('Import watchlist into a local list', 'mdblist_import_watchlist')
                nav.add_action('Import paused viewing into Continue Watching', 'mdblist_import_progress')
                if current.get('sync_id'):
                    nav.add_action('Progress sync status', 'mdblist_sync_status')
                    nav.add_action('Refresh viewing progress','mdblist_refresh_progress')
                    if not current.get('history_sync'):
                        nav.add_action('Enable watched sync','mdblist_enable_history')
                    nav.add_action('Turn off progress sync', 'mdblist_disable_sync')
                else:
                    nav.add_action('Enable progress sync', 'mdblist_enable_sync')
                nav.add_action('Disconnect MDBList', 'mdblist_disconnect')
            else:
                nav.add_action('Connect MDBList', 'mdblist_connect')
            nav.add_folder('Local lists on this device', 'library_home')
        else:
            watchlist(nav, addon, state, current, params.get('cursor', ''))
    except MDBError as error:
        xbmcgui.Dialog().ok(TITLE, MESSAGES.get(error.code, 'MDBList could not load the watchlist. Try again.'))
    nav.end('videos')


def watchlist(nav, addon, state, current, cursor):
    from .catalogue.cards import add_title

    client, current = connected_client(state, current)
    rows, next_cursor = mdblist_import.watchlist_page(client, cursor)
    if (state.connection() or {}).get('generation') != current['generation']:
        raise MDBError('connection_changed')
    for row in rows:
        add_title(nav, addon, safe_label(row['title'], TITLE), row['media'], row['tmdb_id'])
    if next_cursor:
        nav.add_folder('Next page', 'mdblist_watchlist', params={'cursor': next_cursor})
    elif not rows:
        xbmcgui.Dialog().ok(TITLE, 'There are no films or shows to display in this watchlist.')
