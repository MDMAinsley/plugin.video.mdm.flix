"""Read-only MDBList account and watchlist screens."""
import time

import xbmc
import xbmcgui

from .mdblist_account import State
from .mdblist_client import CLIENT_ID, Client, DeviceFlow, MDBError
from . import mdblist_import
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
}


def safe_label(value, default):
    if not isinstance(value, str):
        return default
    return ''.join(c for c in value[:200] if c.isprintable()).replace('[', '［').replace(']', '］').strip() or default


def connect(state):
    flow = DeviceFlow(CLIENT_ID)
    session = flow.begin()
    progress = xbmcgui.DialogProgress()
    text = 'On your phone, open '+session['verification_uri']+'\nEnter code '+session['user_code']
    progress.create('Connect MDBList', text)
    monitor = xbmc.Monitor()
    deadline = time.monotonic()+session['expires_in']
    interval = session['interval']
    try:
        while True:
            next_poll = time.monotonic()+interval
            while time.monotonic() < min(next_poll, deadline):
                if progress.iscanceled() or monitor.waitForAbort(.2):
                    return False
            if time.monotonic() >= deadline:
                raise MDBError('expired_token')
            if progress.iscanceled() or monitor.abortRequested():
                return False
            try:
                tokens = flow.poll(session['device_code'])
            except MDBError as error:
                if error.code == 'authorization_pending':
                    continue
                if error.code == 'slow_down':
                    interval += 5
                    continue
                raise
            account = Client(token=tokens['access_token']).account()
            if progress.iscanceled() or monitor.abortRequested():
                return False
            if not state.connect(account, tokens):
                raise MDBError('connection_changed')
            return True
    finally:
        progress.close()


def action(addon, action_name):
    dialog = xbmcgui.Dialog()
    try:
        state = State(addon)
        current = state.connection()
        if action_name == 'mdblist_connect' and not current:
            if connect(state):
                xbmc.executebuiltin('Container.Refresh')
        elif action_name == 'mdblist_disconnect' and current:
            if dialog.yesno(TITLE, 'Disconnect MDBList on this device?', 'Cancel', 'Disconnect'):
                if state.disconnect(current):
                    xbmc.executebuiltin('Container.Refresh')
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
                nav.add_action('Import watchlist into a local list', 'mdblist_import_watchlist')
                nav.add_action('Import paused viewing into Continue Watching', 'mdblist_import_progress')
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
