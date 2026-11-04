"""A seekable, session-only timing draft bound to the owned playing file."""
import json

import xbmc
import xbmcgui

from resources.lib.playback import timing_rules as rules
from resources.lib.playback.episode_policy import EpisodeError, finite
from resources.lib.playback.timing_store import Store, TimingError

PROPERTY = 'plugin.video.mdm.flix.marking.v1'


def identity(context):
    return [context['token'], context['audio_file'], context['fingerprint'],
            context['item']['tmdb_id'], context['item']['season'], context['item']['episode']]


def draft(context):
    try:
        raw = xbmcgui.Window(10000).getProperty(PROPERTY)
        value = json.loads(raw) if raw and len(raw) <= 2048 else None
        if (isinstance(value, dict) and value.get('identity') == identity(context)
                and value.get('kind') in ('intro', 'outro')):
            if value.get('start') is not None:
                finite(value['start'], 0, context['duration'])
            return value
    except (ValueError, RuntimeError, AttributeError, EpisodeError):
        pass
    return None


def save(value):
    xbmcgui.Window(10000).setProperty(PROPERTY, json.dumps(value))


def clear():
    xbmcgui.Window(10000).clearProperty(PROPERTY)


def panel(addon, token, kind='intro'):
    from resources.lib.playback.timing_ui import playing, same, stamp
    context = playing()
    if not context or context['token'] != token or kind not in ('intro', 'outro'):
        return
    state = draft(context)
    if state is None or state['kind'] != kind:
        text = ('Mark the {} while this episode plays? Seek with the controls in this panel '
                'or return to the video and reopen it. The range will be saved on this device.').format(kind)
        if not xbmcgui.Dialog().yesno('Mark ' + kind, text):
            return
        if not same(context):
            return
        state = dict(identity=identity(context), kind=kind, start=None)
        save(state)
    try:
        while same(context):
            position = finite(xbmc.Player().getTime(), 0, context['duration'])
            beginning = state['start']
            title = 'Mark {} · {}'.format(kind, 'start' if beginning is None else 'end')
            primary = 'Mark start now' if beginning is None else 'Mark end now · start ' + stamp(beginning)
            labels = [primary, 'Back 10 seconds', 'Forward 10 seconds',
                      'Return to video · keep draft', 'Reset start', 'Cancel marking']
            choice = xbmcgui.Dialog().select(title, labels)
            if choice < 0 or choice == 3 or not same(context):
                return
            if choice == 5:
                clear()
                return
            if choice == 4:
                state['start'] = None
                save(state)
            elif choice in (1, 2):
                now = finite(xbmc.Player().getTime(), 0, context['duration'])
                xbmc.Player().seekTime(max(0, min(context['duration'] - 1, now + (-10 if choice == 1 else 10))))
                return
            elif choice == 0:
                position = finite(xbmc.Player().getTime(), 0, context['duration'])
                if beginning is None:
                    state['start'] = position
                    save(state)
                    xbmcgui.Dialog().notification('Mark ' + kind, 'Start saved at ' + stamp(position) + '. Seek to the end, then reopen marking.')
                    return
                row = dict(kind=kind, start=beginning, end=position)
                if not rules.interval(row, context['duration']):
                    xbmcgui.Dialog().ok('Mark ' + kind, 'That range is invalid. Your start is still saved. Seek to the correct end and try again.')
                    return
                if not same(context):
                    return
                Store(addon).confirm(context['fingerprint'], row, context['duration'])
                clear()
                xbmcgui.Dialog().notification('Mark ' + kind, 'Timing saved on this device.')
                return
    except (TimingError, EpisodeError, RuntimeError) as error:
        xbmcgui.Dialog().ok('Mark ' + kind, str(error))
