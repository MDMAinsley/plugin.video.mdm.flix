from resources.lib.constants import (
    ACTION_MOVIES,
    ACTION_TVSHOWS,
    ACTION_SEARCH,
    ACTION_TOOLS,
)


def show(nav):
    nav.add_folder("Movies", ACTION_MOVIES)
    nav.add_folder("TV Shows", ACTION_TVSHOWS)
    nav.add_folder("Search", ACTION_SEARCH)
    nav.add_folder("Tools / Settings", ACTION_TOOLS)
    nav.end()