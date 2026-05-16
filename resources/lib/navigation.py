# -*- coding: utf-8 -*-

from urllib.parse import urlencode

import xbmcplugin

from resources.lib.metadata.listitem import create_folder_item, create_playable_item


class Navigator:
    def __init__(self, handle, base_url):
        self.handle = handle
        self.base_url = base_url

    def build_url(self, **params):
        return f"{self.base_url}?{urlencode(params)}"

    def add_folder(self, label, action, params=None, artwork=None, info=None):
        params = params or {}
        params["action"] = action

        url = self.build_url(**params)
        item = create_folder_item(label, artwork=artwork, info=info)

        xbmcplugin.addDirectoryItem(
            handle=self.handle,
            url=url,
            listitem=item,
            isFolder=True,
        )

    def add_playable(self, label, action, params=None, artwork=None, info=None):
        params = params or {}
        params["action"] = action

        url = self.build_url(**params)
        item = create_playable_item(label, artwork=artwork, info=info)

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