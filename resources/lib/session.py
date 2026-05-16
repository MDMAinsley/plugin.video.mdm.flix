# -*- coding: utf-8 -*-

import json
import os

import xbmc
import xbmcvfs
import xbmcaddon

from resources.lib.constants import ADDON_ID

SESSION_FILE = "sources_session.json"


def _profile_dir():
    addon = xbmcaddon.Addon(ADDON_ID)
    path = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    xbmcvfs.mkdirs(path)
    return path


def _session_path():
    return os.path.join(_profile_dir(), SESSION_FILE)


def clear_sources():
    path = _session_path()
    if xbmcvfs.exists(path):
        xbmcvfs.delete(path)


def store_sources(sources):
    data = {}

    for index, source in enumerate(sources or []):
        source_id = source.get("source_id") or str(index)
        source["source_id"] = source_id
        data[source_id] = source

    path = _session_path()

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)

    return data


def get_source(source_id):
    path = _session_path()

    if not xbmcvfs.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        return data.get(source_id)

    except Exception as exc:
        xbmc.log(f"[MDM Flix] Failed to read source session: {exc}", xbmc.LOGERROR)
        return None