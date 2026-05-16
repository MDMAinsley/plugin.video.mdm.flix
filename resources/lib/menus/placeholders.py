import xbmcgui

from resources.lib.constants import ACTION_SOURCES
from resources.lib.metadata.artwork import build_artwork
from resources.lib.metadata.infolabels import build_video_info


def show_movie_list(nav, title):
    artwork = build_artwork(
        poster="DefaultVideo.png",
        fanart="",
        icon="DefaultVideo.png",
    )

    info = build_video_info(
        media_type="movie",
        title="MDM Test Movie",
        plot="A placeholder movie used to test MDM Flix navigation, metadata, source selection and playback.",
        year=2026,
        genre="Test",
        runtime=600,
        rating=7.5,
    )

    nav.add_folder(
        "MDM Test Movie",
        ACTION_SOURCES,
        params={
            "media_type": "movie",
            "title": "MDM Test Movie",
            "tmdb_id": "0",
            "year": "2026",
            "plot": "A placeholder movie used to test MDM Flix navigation, metadata, source selection and playback.",
            "runtime": "600",
            "rating": "7.5",
            "genre": "Test",
        },
        artwork=artwork,
        info=info,
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