from resources.lib.constants import (
    ACTION_OPEN_SETTINGS,
    ACTION_PROVIDER_SETTINGS,
    ACTION_DIAGNOSTICS,
    ACTION_TEST_PLAYBACK,
)


def show(nav, addon):
    nav.add_action("Open MDM Flix Settings", ACTION_OPEN_SETTINGS)
    nav.add_action("Provider Settings", ACTION_PROVIDER_SETTINGS)
    nav.add_action("Diagnostics", ACTION_DIAGNOSTICS)
    nav.add_playable("Test Playback", ACTION_TEST_PLAYBACK)
    nav.end()