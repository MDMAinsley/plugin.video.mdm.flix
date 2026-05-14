from resources.lib.constants import (
    ACTION_TV_TRENDING,
    ACTION_TV_POPULAR,
    ACTION_SEARCH_TV,
)


def show(nav):
    nav.add_folder("Trending TV Shows", ACTION_TV_TRENDING)
    nav.add_folder("Popular TV Shows", ACTION_TV_POPULAR)
    nav.add_folder("Search TV Shows", ACTION_SEARCH_TV)
    nav.end("tvshows")