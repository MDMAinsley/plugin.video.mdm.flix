import xbmcgui

from resources.lib.catalogue.tmdb import TMDB

TMDB_LOGO = "https://www.themoviedb.org/assets/v4/logos/v2/blue_square_2-d537fb228cf3ded904ef09b136fe3fec72548ebc1fea3fbbd1ad9e36364db38b.svg"

def diagnostics(nav, addon, core):
    client = TMDB(addon, core)
    from resources.lib.kodi_addons import get_addon
    from resources.lib.playback.alldebrid import AllDebrid
    debrid = AllDebrid(addon)
    coco = get_addon("script.module.cocoscrapers")
    text = "Flix: {}\nCore: {}\nTMDB credentials: {}\nMetadata language: {}\nCocoScrapers: {}\nProvider setting: {}\nPlayback mode: {}\nAllDebrid enabled: {}\nAllDebrid credentials: {}\n\nAvailability: checked on selection\nSource session expiry: 30 minutes\nSearch limit: 45 seconds\nAllDebrid preparation limit: 45 seconds total (after source search)\nMDM Link: available through Provider Settings".format(
        addon.getAddonInfo("version"), getattr(core, "__version__", "unavailable"),
        "configured" if client.configured else "missing", client.language,
        coco.getAddonInfo("version") if coco else "missing / disabled",
        addon.getSetting("scraper_provider") or "Auto", addon.getSetting("playback_mode") or "Source Select",
        "yes" if debrid.enabled else "no", "configured" if debrid.key else "missing")
    link = get_addon('script.mdm.link')
    if link:
        from mdmlink.api import status
        import json
        text += '\n\nMDM Link status (no credentials/addresses):\n' + json.dumps(status(link), indent=2)
    xbmcgui.Dialog().textviewer("MDM Flix diagnostics", text)
    nav.end()


def about(nav):
    nav.add_action("TMDB — catalogue and artwork credits", "tmdb_credit_notice",
                   artwork={"icon": TMDB_LOGO, "thumb": TMDB_LOGO},
                   info={"plot": "This product uses the TMDB API but is not endorsed or certified by TMDB.\nhttps://www.themoviedb.org"})
    xbmcgui.Dialog().textviewer("About MDM Flix / TMDB", "MDM Flix\n\nThis product uses the TMDB API but is not endorsed or certified by TMDB.\n\nhttps://www.themoviedb.org\n\nTMDB supplies catalogue data and artwork. Playback provider integration is separate.")
    nav.end()
