from urllib.parse import parse_qsl

import xbmcplugin

from resources.lib.constants import (
    ACTION_HOME,
    ACTION_MOVIES,
    ACTION_TVSHOWS,
    ACTION_SEARCH,
    ACTION_TOOLS,
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

        else:
            from resources.lib.menus.home import show
            show(nav)