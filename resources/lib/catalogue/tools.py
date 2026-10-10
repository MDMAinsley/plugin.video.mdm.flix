import xbmcgui

from resources.lib.catalogue.tmdb import TMDB

TMDB_LOGO = "https://www.themoviedb.org/assets/v4/logos/v2/blue_square_2-d537fb228cf3ded904ef09b136fe3fec72548ebc1fea3fbbd1ad9e36364db38b.svg"

def diagnostics(nav, addon, core):
    client = TMDB(addon, core)
    text = "Flix: {}\nCore: {}\nTMDB credentials: {}\nMetadata language: {}\n\nCatalogue browsing: TMDB\nReal-title playback: awaiting provider integration\nDemo playback: Tools → Test Playback".format(
        addon.getAddonInfo("version"), getattr(core, "__version__", "unavailable"),
        "configured" if client.configured else "missing", client.language)
    xbmcgui.Dialog().textviewer("MDM Flix diagnostics", text)
    nav.end()


def about(nav):
    nav.add_action("TMDB — catalogue and artwork credits", "tmdb_credit_notice",
                   artwork={"icon": TMDB_LOGO, "thumb": TMDB_LOGO},
                   info={"plot": "This product uses the TMDB API but is not endorsed or certified by TMDB.\nhttps://www.themoviedb.org"})
    xbmcgui.Dialog().textviewer("About MDM Flix / TMDB", "MDM Flix\n\nThis product uses the TMDB API but is not endorsed or certified by TMDB.\n\nhttps://www.themoviedb.org\n\nTMDB supplies catalogue data and artwork. Playback provider integration is separate.")
    nav.end()
