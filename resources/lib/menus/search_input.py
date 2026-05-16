# -*- coding: utf-8 -*-

import xbmc
import xbmcgui

from resources.lib.constants import ACTION_SOURCES
from resources.lib.metadata.artwork import build_artwork
from resources.lib.metadata.infolabels import build_video_info


def ask_search_query(heading):
    keyboard = xbmc.Keyboard("", heading, False)
    keyboard.doModal()

    if not keyboard.isConfirmed():
        return ""

    return keyboard.getText().strip()


def show_movie_search(nav):
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

    nav.add_folder(
        f"Search Result: {query}",
        ACTION_SOURCES,
        params={
            "media_type": "movie",
            "title": query,
            "tmdb_id": "0",
            "year": "2026",
            "plot": f"Temporary search result for movie query: {query}",
            "runtime": "600",
            "rating": "7.5",
            "genre": "Search Test",
        },
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