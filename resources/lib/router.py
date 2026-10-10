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
    ACTION_AUTOPLAY,
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
            from resources.lib.playback.resolver import play_source
            play_source(self.params.get("source_id", ""), self.addon, self.core, self.log)

        elif action == ACTION_AUTOPLAY:
            from resources.lib.playback.resolver import autoplay
            autoplay(nav, self.addon, self.core, self.log, self.params)

        elif action == ACTION_TEST_PLAYBACK:
            from resources.lib.playback.player import play_test_stream
            play_test_stream()

        elif action == ACTION_OPEN_SETTINGS:
            self.addon.openSettings()
            return

        elif action == ACTION_PROVIDER_SETTINGS:
            from resources.lib.kodi_addons import get_addon
            link=self.addon.getSetting('scraper_provider')=='MDM Link'
            provider = get_addon('script.mdm.link' if link else 'script.module.cocoscrapers')
            if provider:
                if link:
                    from mdmlink.api import migrate
                    migrate(provider,self.addon)
                provider.openSettings()
            else:
                xbmcgui.Dialog().ok('MDM Flix','Install and enable the selected provider to open its settings.')
            return

        elif action in ("alldebrid_authorise", "alldebrid_check", "alldebrid_disconnect"):
            if self.addon.getSetting('scraper_provider')=='MDM Link':
                from resources.lib.kodi_addons import get_addon
                from mdmlink.api import migrate
                from mdmlink.ui import authorise, check_account, disconnect
                target=get_addon('script.mdm.link')
                if not target:
                    xbmcgui.Dialog().ok('MDM Flix','Enable MDM Link before authorising its account.')
                    return
                migrate(target,self.addon)
                handlers={'alldebrid_authorise':authorise,'alldebrid_check':check_account,'alldebrid_disconnect':disconnect}
                handlers[action](target)
                return
            from resources.lib.playback.account import authorise, check_account, disconnect
            handlers = {"alldebrid_authorise": authorise, "alldebrid_check": check_account, "alldebrid_disconnect": disconnect}
            handlers[action](self.addon)
            return

        elif action == ACTION_DIAGNOSTICS:
            from resources.lib.catalogue.tools import diagnostics
            diagnostics(nav, self.addon, self.core)

        elif action in ("about_tmdb", "tmdb_credit_notice"):
            from resources.lib.catalogue.tools import about
            about(nav)

        elif action in (ACTION_MOVIES_TRENDING, ACTION_MOVIES_POPULAR,
                        ACTION_SEARCH_MOVIES, ACTION_TV_TRENDING,
                        ACTION_TV_POPULAR, ACTION_SEARCH_TV,
                        "tv_seasons", "tv_episodes", "catalogue_details", "catalogue_info"):
            from resources.lib.catalogue.browse import show
            params = dict(self.params)
            if action == "catalogue_info":
                params["action"] = "catalogue_details"
            show(nav, self.addon, self.core, params)

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
