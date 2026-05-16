# -*- coding: utf-8 -*-

import xbmc
import xbmcgui

from resources.lib.constants import ACTION_SOURCES, ACTION_AUTOPLAY, PLAYBACK_MODE_AUTOPLAY
from resources.lib.playback.selection import get_playback_mode
from resources.lib.metadata.artwork import build_artwork
from resources.lib.metadata.infolabels import build_video_info


def ask_search_query(heading):
    keyboard = xbmc.Keyboard("", heading, False)
    keyboard.doModal()

    if not keyboard.isConfirmed():
        return ""

    return keyboard.getText().strip()


def show_movie_search(nav, addon=None):
    query = ask_search_query("Search Movies")

    if not query:
        nav.end("movies")
        return

    artwork = build_artwork(
        poster="DefaultVideo.png",
        icon="DefaultVideo.png",
    )

    info = build_video_info(
        media_type="movie",
        title=f"Search Result: {query}",
        plot=f"Temporary search result for movie query: {query}",
        year=2026,
        genre="Search Test",
        runtime=600,
        rating=7.5,
    )

    params = {
        "media_type": "movie",
        "title": query,
        "tmdb_id": "0",
        "year": "2026",
        "plot": f"Temporary search result for movie query: {query}",
        "runtime": "600",
        "rating": "7.5",
        "genre": "Search Test",
    }

    action = ACTION_SOURCES

    if addon and get_playback_mode(addon) == PLAYBACK_MODE_AUTOPLAY:
        action = ACTION_AUTOPLAY

    if action == ACTION_AUTOPLAY:
        nav.add_playable(
            f"Search Result: {query}",
            action,
            params=params,
            artwork=artwork,
            info=info,
        )
    else:
        nav.add_folder(
            f"Search Result: {query}",
            action,
            params=params,
            artwork=artwork,
            info=info,
        )

    nav.end("movies")


def show_tv_search(nav):
    query = ask_search_query("Search TV Shows")

    if not query:
        nav.end("tvshows")
        return

    xbmcgui.Dialog().notification(
        "MDM Flix",
        f"TV search received: {query}",
        xbmcgui.NOTIFICATION_INFO,
        3000,
    )

    nav.end("tvshows")