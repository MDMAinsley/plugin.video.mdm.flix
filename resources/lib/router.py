from urllib.parse import parse_qsl

import xbmc
import xbmcgui

from resources.lib.constants import (
    ACTION_HOME,
    ACTION_MOVIES,
    ACTION_TVSHOWS,
    ACTION_SEARCH,
    ACTION_TOOLS,
    ACTION_SOURCES,
    ACTION_PLAY,
    ACTION_TEST_PLAYBACK,
    ACTION_OPEN_SETTINGS,
    ACTION_PROVIDER_SETTINGS,
    ACTION_DIAGNOSTICS,
    ACTION_MOVIES_TRENDING,
    ACTION_MOVIES_POPULAR,
    ACTION_SEARCH_MOVIES,
    ACTION_TV_TRENDING,
    ACTION_TV_POPULAR,
    ACTION_SEARCH_TV,
)


class Router:
    def __init__(self, addon, core, log, argv):
        self.addon = addon
        self.core = core
        self.log = log
        self.argv = argv

        self.base_url = argv[0]
        self.handle = int(argv[1])
        self.params = dict(parse_qsl(argv[2][1:])) if len(argv) > 2 else {}

    def dispatch(self):
        action = self.params.get("action", ACTION_HOME)

        if self.log:
            self.log.info(f"Routing action: {action}")

        from resources.lib.navigation import Navigator
        nav = Navigator(self.handle, self.base_url)

        if action == ACTION_HOME:
            from resources.lib.menus.home import show
            show(nav)

        elif action == ACTION_MOVIES:
            from resources.lib.menus.movies import show
            show(nav)

        elif action == ACTION_TVSHOWS:
            from resources.lib.menus.tvshows import show
            show(nav)

        elif action == ACTION_SEARCH:
            from resources.lib.menus.search import show
            show(nav)

        elif action == ACTION_TOOLS:
            from resources.lib.menus.tools import show
            show(nav, self.addon)

        elif action == ACTION_SOURCES:
            from resources.lib.playback.resolver import show_sources
            show_sources(nav, self.addon, self.core, self.log, self.params)

        elif action == ACTION_PLAY:
            from resources.lib.playback.player import play_source
            play_source(
                self.params.get("source_id", ""),
                self.params.get("label", "MDM Flix"),
            )

        elif action == ACTION_TEST_PLAYBACK:
            from resources.lib.playback.player import play_test_stream
            play_test_stream()

        elif action == ACTION_OPEN_SETTINGS:
            self.addon.openSettings()
            nav.end()

        elif action == ACTION_PROVIDER_SETTINGS:
            self.addon.openSettings()
            nav.end()

        elif action == ACTION_DIAGNOSTICS:
            xbmcgui.Dialog().notification(
                "MDM Flix",
                "Diagnostics not built yet.",
                xbmcgui.NOTIFICATION_INFO,
                3000,
            )
            nav.end()

        elif action == ACTION_MOVIES_TRENDING:
            from resources.lib.menus.placeholders import show_movie_list
            show_movie_list(nav, "Trending Movies")

        elif action == ACTION_MOVIES_POPULAR:
            from resources.lib.menus.placeholders import show_movie_list
            show_movie_list(nav, "Popular Movies")

        elif action == ACTION_SEARCH_MOVIES:
            from resources.lib.menus.search_input import show_movie_search
            show_movie_search(nav)

        elif action == ACTION_TV_TRENDING:
            from resources.lib.menus.placeholders import show_tv_list
            show_tv_list(nav, "Trending TV Shows")

        elif action == ACTION_TV_POPULAR:
            from resources.lib.menus.placeholders import show_tv_list
            show_tv_list(nav, "Popular TV Shows")

        elif action == ACTION_SEARCH_TV:
            from resources.lib.menus.search_input import show_tv_search
            show_tv_search(nav)

        else:
            if self.log:
                self.log.warning(f"Unknown route: {action}")
            else:
                xbmc.log(f"[MDM Flix] Unknown route: {action}", xbmc.LOGWARNING)

            xbmcgui.Dialog().notification(
                "MDM Flix",
                f"Unknown route: {action}",
                xbmcgui.NOTIFICATION_WARNING,
                3000,
            )
            nav.end()