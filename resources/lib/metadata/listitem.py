# -*- coding: utf-8 -*-

import xbmcgui

from resources.lib.metadata.artwork import apply_artwork
from resources.lib.metadata.infolabels import apply_video_info


def create_folder_item(label, artwork=None, info=None):
    item = xbmcgui.ListItem(label=label)

    apply_artwork(item, artwork)
    apply_video_info(item, info)

    return item


def create_playable_item(label, artwork=None, info=None):
    item = xbmcgui.ListItem(label=label)
    item.setProperty("IsPlayable", "true")

    apply_artwork(item, artwork)
    apply_video_info(item, info)

    return item