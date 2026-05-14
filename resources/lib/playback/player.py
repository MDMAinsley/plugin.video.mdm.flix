import sys

import xbmcgui
import xbmcplugin


def play_url(url, label="MDM Flix"):
    if not url:
        xbmcgui.Dialog().notification(
            "MDM Flix",
            "No playable URL found.",
            xbmcgui.NOTIFICATION_ERROR,
            3000,
        )
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), False, xbmcgui.ListItem())
        return

    item = xbmcgui.ListItem(label=label, path=url)
    item.setProperty("IsPlayable", "true")

    xbmcplugin.setResolvedUrl(
        int(sys.argv[1]),
        True,
        item,
    )


def play_test_stream():
    play_url(
        "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
        "MDM Flix Test Stream",
    )