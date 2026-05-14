import xbmcgui

from resources.lib.constants import ACTION_PLAY
from resources.lib.models.media_item import from_params


def show_sources(nav, addon, core, log, params):
    from resources.lib.providers.manager import ProviderManager

    item = from_params(params)

    manager = ProviderManager(addon=addon, core=core, log=log)
    sources = manager.search_sources(item)

    if not sources:
        xbmcgui.Dialog().notification(
            "MDM Flix",
            "No sources found.",
            xbmcgui.NOTIFICATION_WARNING,
            3000,
        )
        nav.end()
        return

    for index, source in enumerate(sources):
        label = source.get("label", "Unknown Source")
        quality = source.get("quality", "Unknown")
        provider = source.get("provider", "Unknown Provider")
        url = source.get("url", "")

        nav.add_playable(
            f"{label} [{quality}] - {provider}",
            ACTION_PLAY,
            params={
                "source_index": str(index),
                "url": url,
                "label": label,
            },
        )

    nav.end("videos")