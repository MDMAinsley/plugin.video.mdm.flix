# -*- coding: utf-8 -*-

import xbmcgui

from resources.lib.constants import ACTION_PLAY, PLAYBACK_MODE_AUTOPLAY
from resources.lib.models.media_item import from_params
from resources.lib.session import store_sources
from resources.lib.playback.selection import get_playback_mode, sort_sources, pick_best_source
from resources.lib.playback.player import play_source


def show_sources(nav, addon, core, log, params):
    from resources.lib.providers.manager import ProviderManager

    item = from_params(params)

    manager = ProviderManager(addon=addon, core=core, log=log)
    sources = manager.search_sources(item)
    sources = sort_sources(sources)

    if not sources:
        xbmcgui.Dialog().notification(
            "MDM Flix",
            "No sources found.",
            xbmcgui.NOTIFICATION_WARNING,
            3000,
        )
        nav.end()
        return

    store_sources(sources)

    mode = get_playback_mode(addon)

    if mode == PLAYBACK_MODE_AUTOPLAY:
        best = pick_best_source(sources)

        if not best:
            xbmcgui.Dialog().notification(
                "MDM Flix",
                "No playable source found.",
                xbmcgui.NOTIFICATION_WARNING,
                3000,
            )
            nav.end()
            return

        if log:
            log.info(f"Autoplay selected source: {best.get('label')}")

        play_source(best.get("source_id", ""), best.get("label", "MDM Flix"))
        return

    for source in sources:
        source_id = source.get("source_id", "")
        label = source.get("label", "Unknown Source")
        quality = source.get("quality", "Unknown")
        provider = source.get("provider_name", "Unknown Provider")

        nav.add_playable(
            f"{label} [{quality}] - {provider}",
            ACTION_PLAY,
            params={
                "source_id": source_id,
                "label": label,
            },
        )

    nav.end("videos")

def autoplay(nav, addon, core, log, params):
    from resources.lib.providers.manager import ProviderManager

    item = from_params(params)

    manager = ProviderManager(addon=addon, core=core, log=log)
    sources = manager.search_sources(item)
    sources = sort_sources(sources)

    if not sources:
        xbmcgui.Dialog().notification(
            "MDM Flix",
            "No sources found.",
            xbmcgui.NOTIFICATION_WARNING,
            3000,
        )
        return

    store_sources(sources)

    best = pick_best_source(sources)

    if not best:
        xbmcgui.Dialog().notification(
            "MDM Flix",
            "No playable source found.",
            xbmcgui.NOTIFICATION_WARNING,
            3000,
        )
        return

    if log:
        log.info(f"Autoplay selected source: {best.get('label')}")

    play_source(best.get("source_id", ""), best.get("label", "MDM Flix"))
    return