import xbmcgui

from resources.lib.constants import ACTION_SOURCES


def show_movie_list(nav, title):
    nav.add_folder(
        "MDM Test Movie",
        ACTION_SOURCES,
        params={
            "media_type": "movie",
            "title": "MDM Test Movie",
            "tmdb_id": "0",
        },
    )

    nav.end("movies")


def show_tv_list(nav, title):
    xbmcgui.Dialog().notification(
        "MDM Flix",
        f"{title} not built yet.",
        xbmcgui.NOTIFICATION_INFO,
        2500,
    )

    nav.end("tvshows")


def show_search_placeholder(nav, title):
    xbmcgui.Dialog().notification(
        "MDM Flix",
        f"{title} not built yet.",
        xbmcgui.NOTIFICATION_INFO,
        2500,
    )

    nav.end("videos")