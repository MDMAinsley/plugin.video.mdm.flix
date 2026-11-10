"""Signal saved changes to MDM Skin's quiet Home directories."""
import time

import xbmcgui


def invalidate(row):
    try:
        xbmcgui.Window(10000).setProperty('mdm_home_' + row + '_revision', str(time.monotonic_ns()))
    except RuntimeError:
        pass  # Kodi can close its Home window before the final progress write.
