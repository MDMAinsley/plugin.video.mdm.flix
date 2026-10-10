import sys
from urllib.parse import urlsplit
import xbmc
import xbmcgui
import xbmcplugin
from resources.lib.playback.files import web_url
from resources.lib.playback.errors import PlaybackError


def failed():
    xbmcplugin.setResolvedUrl(int(sys.argv[1]),False,xbmcgui.ListItem())


def listitem(url,label):
    if not web_url(url): raise PlaybackError('No valid playable URL was returned.')
    item=xbmcgui.ListItem(label=label,path=url)
    item.setProperty('IsPlayable','true'); item.setContentLookup(False)
    path=urlsplit(url).path.lower()
    if path.endswith('.m3u8'):
        item.setMimeType('application/vnd.apple.mpegurl')
        # Kodi can play ordinary HLS natively without forcing an optional addon.
    elif path.endswith('.mpd'):
        from resources.lib.kodi_addons import is_addon_installed
        if not is_addon_installed('inputstream.adaptive'): raise PlaybackError('Install and enable InputStream Adaptive for this DASH source.')
        item.setMimeType('application/dash+xml'); item.setProperty('inputstream','inputstream.adaptive')
    return item


def play_url(url,label='MDM Flix'):
    item=listitem(url,label)
    xbmcplugin.setResolvedUrl(int(sys.argv[1]),True,item)


def direct_play_url(url,label='MDM Flix'):
    xbmc.Player().play(url,listitem(url,label))


def play_test_stream():
    play_url('https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8','MDM Flix Test Stream')
