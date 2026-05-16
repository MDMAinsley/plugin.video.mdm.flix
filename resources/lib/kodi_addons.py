# -*- coding: utf-8 -*-

import xbmcaddon


def is_addon_installed(addon_id):
    try:
        xbmcaddon.Addon(addon_id)
        return True
    except Exception:
        return False


def get_addon(addon_id):
    try:
        return xbmcaddon.Addon(addon_id)
    except Exception:
        return None