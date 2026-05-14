from resources.lib.constants import ACTION_SEARCH_MOVIES, ACTION_SEARCH_TV


def show(nav):
    nav.add_folder("Search Movies", ACTION_SEARCH_MOVIES)
    nav.add_folder("Search TV Shows", ACTION_SEARCH_TV)
    nav.end()