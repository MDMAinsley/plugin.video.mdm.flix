from urllib.parse import urlencode

import xbmcgui
import xbmcplugin

from resources.lib.constants import ADDON_ID


class Navigator:
    def __init__(self, handle, base_url):
        self.handle = handle
        self.base_url = base_url

    def build_url(self, **params):
        return f"{self.base_url}?{urlencode(params)}"

    def add_folder(self, label, action, params=None, icon=None, fanart=None):
        params = params or {}
        params["action"] = action

        url = self.build_url(**params)

        item = xbmcgui.ListItem(label=label)
        item.setArt({
            "icon": icon or "DefaultFolder.png",
            "thumb": icon or "DefaultFolder.png",
            "fanart": fanart or "",
        })

        xbmcplugin.addDirectoryItem(
            handle=self.handle,
            url=url,
            listitem=item,
            isFolder=True,
        )

    def add_playable(self, label, action, params=None, icon=None, fanart=None):
        params = params or {}
        params["action"] = action

        url = self.build_url(**params)

        item = xbmcgui.ListItem(label=label)
        item.setProperty("IsPlayable", "true")
        item.setArt({
            "icon": icon or "DefaultVideo.png",
            "thumb": icon or "DefaultVideo.png",
            "fanart": fanart or "",
        })

        xbmcplugin.addDirectoryItem(
            handle=self.handle,
            url=url,
            listitem=item,
            isFolder=False,
        )

    def end(self, content_type=None):
        if content_type:
            xbmcplugin.setContent(self.handle, content_type)

        xbmcplugin.endOfDirectory(self.handle)