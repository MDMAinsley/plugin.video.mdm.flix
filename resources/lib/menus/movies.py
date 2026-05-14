def show(nav):
    nav.add_folder("Trending Movies", "movies_trending")
    nav.add_folder("Popular Movies", "movies_popular")
    nav.add_folder("Search Movies", "search_movies")
    nav.end("movies")from resources.lib.constants import (
    ACTION_MOVIES_TRENDING,
    ACTION_MOVIES_POPULAR,
    ACTION_SEARCH_MOVIES,
    ACTION_SOURCES,
)


def show(nav):
    nav.add_folder("Trending Movies", ACTION_MOVIES_TRENDING)
    nav.add_folder("Popular Movies", ACTION_MOVIES_POPULAR)
    nav.add_folder("Search Movies", ACTION_SEARCH_MOVIES)

    nav.add_folder(
        "Test Movie Sources",
        ACTION_SOURCES,
        params={
            "media_type": "movie",
            "title": "MDM Test Movie",
            "tmdb_id": "0",
        },
    )

    nav.end("movies")