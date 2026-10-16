"""Shared movie/show/episode click semantics across browse/search/home rows."""
from urllib.parse import urlencode
import xbmcgui
from resources.lib.catalogue.tmdb import TMDB, CatalogueError, number


def add_title(nav, addon, label, media, identifier, artwork=None, info=None,
              season=None, episode=None):
    if media not in ("movie", "tv"):
        raise CatalogueError("Invalid title type.")
    params = {"media_type": media, "tmdb_id": number(identifier, 1)}
    is_episode = season is not None and episode is not None
    if is_episode:
        if media != "tv":
            raise CatalogueError("Invalid episode link.")
        params.update(season=number(season), episode=number(episode, 1))
    context = [("Title information", "RunPlugin(plugin://plugin.video.mdm.flix/?" +
        urlencode(dict(params, action="title_info")) + ")")]
    common = dict(params=params, artwork=artwork, info=info, context_menu=context)
    if media == "tv" and not is_episode:
        nav.add_folder(label, "tv_seasons", **common)
    elif addon.getSetting("playback_mode") == "Autoplay":
        nav.add_playable(label, "autoplay", **common)
    else:
        nav.add_folder(label, "sources", **common)


def show_info(addon, core, params):
    try:
        from resources.lib.catalogue.browse import info
        client = TMDB(addon, core)
        media = params.get("media_type", "movie")
        if media not in ("movie", "tv"):
            raise CatalogueError("Invalid title type.")
        identifier = number(params.get("tmdb_id"), 1)
        parent = None
        is_episode = "season" in params or "episode" in params
        if is_episode:
            if media != "tv":
                raise CatalogueError("Invalid episode link.")
            season = number(params.get("season")); episode = number(params.get("episode"), 1)
            parent = client.details("tv", identifier)
            data = client.request("tv/{}/season/{}/episode/{}".format(identifier, season, episode), ttl=3600)
        else:
            data = client.details(media, identifier)
        metadata = info(data, "episode" if is_episode else "movie" if media == "movie" else "tvshow", parent)
        lines = [metadata["plot"]]
        if metadata.get("premiered"):
            lines.append("Released: " + metadata["premiered"])
        if metadata.get("genre"):
            lines.append("Genres: " + ", ".join(metadata["genre"]))
        if "rating" in metadata:
            lines.append("TMDB rating: " + str(metadata["rating"]))
        if metadata.get("duration"):
            lines.append("Runtime: {} minutes".format(int(metadata["duration"] / 60)))
        lines.append("TMDB {} ID: {}".format("show" if media == "tv" else "movie", identifier))
        if is_episode:
            lines.append("Season {} · Episode {}".format(season, episode))
        xbmcgui.Dialog().textviewer(metadata["title"], "\n\n".join(lines))
    except CatalogueError as error:
        xbmcgui.Dialog().ok("MDM Flix", str(error))
    # This RunPlugin action opens only the dialog. It does not create a new
    # directory, start scraping, resolve playback or change the selected title.
