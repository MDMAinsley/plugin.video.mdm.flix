"""One playback menu for marking, ratings and timing information."""
import xbmcgui

PROPERTY = 'MDM.Flix.EpisodeControls'


def available(value):
    try:
        window = xbmcgui.Window(10000)
        if value:
            window.setProperty(PROPERTY, 'true')
        else:
            window.clearProperty(PROPERTY)
    except (AttributeError, RuntimeError):
        pass


def show(addon, core):
    from resources.lib.playback import marking, timing_feedback, timing_ui
    context = timing_ui.playing()
    if not context:
        xbmcgui.Dialog().ok('Intro / outro controls', 'Start an episode in MDM Flix first.')
        return
    draft = marking.draft(context)
    labels = ['Mark intro', 'Mark outro', 'Rate intro timing', 'Rate outro timing',
              'Timing information', 'Timing sharing and upload status', 'Shared timings / file check']
    if draft:
        index = 0 if draft['kind'] == 'intro' else 1
        labels[index] = 'Continue marking ' + draft['kind']
        if draft['start'] is not None:
            labels[index] += ' · start ' + timing_ui.stamp(draft['start'])
    selected = xbmcgui.Dialog().select('Intro / outro controls', labels)
    if selected < 0 or not timing_ui.same(context):
        return
    if selected in (0, 1):
        marking.panel(addon, context['token'], 'intro' if selected == 0 else 'outro')
    elif selected in (2, 3):
        timing_feedback.panel(addon, context['token'], 'intro' if selected == 2 else 'outro')
    elif selected == 4:
        timing_ui.action(addon, core, {})
    elif selected == 5:
        from resources.lib.playback.contributions import manage
        manage(addon)
    elif selected == 6:
        from resources.lib.playback.native_identity import manage
        manage(addon)
