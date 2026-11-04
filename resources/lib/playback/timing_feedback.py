"""Current timing observations and optional local Good/Bad/correction actions."""
import json

import xbmcgui

from resources.lib.playback import timing_rules as rules
from resources.lib.playback.feedback_store import Feedback
from resources.lib.playback.timing_store import TimingError

PROPERTY = 'plugin.video.mdm.flix.observed.'


def remember(context, row, kind):
    if not context or not row:
        return
    bounds = rules.interval(row, context['duration'])
    if not bounds:
        return
    value = dict(token=context['token'], file_id=context['audio_file'],
                 duration=context['duration'],
                 kind=kind, start=bounds[0], end=bounds[1],
                 marker_id=row.get('marker_id'), revision=row.get('revision'))
    try:
        encoded = json.dumps(value)
        window = xbmcgui.Window(10000)
        if window.getProperty(PROPERTY + kind) != encoded:
            window.setProperty(PROPERTY + kind, encoded)
    except (AttributeError, RuntimeError, TypeError):
        pass


def observation(context, kind):
    try:
        raw = xbmcgui.Window(10000).getProperty(PROPERTY + kind)
        value = json.loads(raw) if raw and len(raw) <= 2048 else None
        if (isinstance(value, dict) and value.get('token') == context['token']
                and value.get('file_id') == context['audio_file']
                and rules.number(value.get('duration'),60) is not None
                and abs(value['duration']-context['duration'])<=2
                and value.get('kind') == kind and rules.interval(value, context['duration'])):
            return value
    except (AttributeError, RuntimeError, ValueError, TypeError):
        pass
    return None


def panel(addon, token, kind='intro'):
    from resources.lib.playback.timing_ui import playing, same
    from resources.lib.playback.marking import panel as mark
    context = playing()
    if not context or context['token'] != token or kind not in ('intro', 'outro'):
        return
    row = observation(context, kind)
    if not row:
        if xbmcgui.Dialog().yesno('Timing feedback', 'No current '+kind+' timing is available. Would you like to mark it?'):
            mark(addon, token, kind)
        return
    choice = xbmcgui.Dialog().select('Rate '+kind+' timing · saved on this device',
                                    ['Good', 'Bad', 'Correct timing using playback', 'Not now'])
    if choice < 0 or choice == 3 or not same(context):
        return
    if choice == 2:
        mark(addon, token, kind)
        return
    try:
        Feedback(addon).save(context, row, 'good' if choice == 0 else 'bad')
        xbmcgui.Dialog().notification('Timing feedback', 'Rating saved on this device.')
    except TimingError as error:
        xbmcgui.Dialog().ok('Timing feedback', str(error))


def manage(addon):
    try:
        store = Feedback(addon)
        choice = xbmcgui.Dialog().select('Timing feedback',
            [str(store.count())+' local ratings/corrections',
             'Delete local timing feedback', 'Back'])
        if choice == 1 and xbmcgui.Dialog().yesno('Delete feedback?', 'Delete ratings and correction records saved on this device? Saved intro and outro timings will stay available.'):
            store.clear()
        elif choice == 0:
            xbmcgui.Dialog().ok('Timing feedback', 'Feedback is saved locally. Shared submissions and reviewer sign-in are still being connected.')
    except TimingError as error:
        xbmcgui.Dialog().ok('Timing feedback', str(error))
