import xbmcgui

from resources.lib.constants import ACTION_PLAY
from resources.lib.models.media_item import from_params
from resources.lib.session import store_sources


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

    store_sources(sources)

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