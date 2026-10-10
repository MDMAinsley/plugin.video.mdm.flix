import xbmc
from resources.lib import device_policy
import xbmcgui

from resources.lib.catalogue.tmdb import TMDB, CatalogueError, number
from resources.lib.metadata.infolabels import build_video_info

LIST_ROUTES = {
    "movies_trending": ("movie", "trending"),
    "movies_popular": ("movie", "popular"),
    "search_movies": ("movie", "search"),
    "tv_trending": ("tv", "trending"),
    "tv_popular": ("tv", "popular"),
    "search_tv": ("tv", "search"),
}


def artwork(raw, parent=None, addon=None):
    parent = parent or {}
    light = device_policy.artwork_mode(addon) if addon else False
    poster = TMDB.image(raw.get("poster_path") or parent.get("poster_path"), "w342" if light else "w500")
    return {"poster": poster, "icon": poster or "DefaultVideo.png",
            "fanart": "" if light else TMDB.image(raw.get("backdrop_path") or parent.get("backdrop_path"), "w1280"),
            "thumb": TMDB.image(raw.get("still_path"), "w300" if light else "w500") or poster}


def info(raw, media, parent=None):
    parent = parent or {}
    title = raw.get("title") or raw.get("name") or "Untitled"
    title = title if isinstance(title, str) else "Untitled"
    date = raw.get("release_date") or raw.get("first_air_date") or raw.get("air_date") or ""
    year = int(date[:4]) if isinstance(date, str) and date[:4].isdigit() else None
    date = date if isinstance(date, str) else ""
    genre_rows = raw.get("genres")
    genres = [g["name"] for g in (genre_rows if isinstance(genre_rows, list) else []) if isinstance(g, dict) and isinstance(g.get("name"), str)]
    runtime = raw.get("runtime")
    runtime = runtime * 60 if isinstance(runtime, (int, float)) and runtime > 0 else None
    plot = raw.get("overview")
    plot = plot if isinstance(plot, str) and plot else "No overview available."
    result = build_video_info(media, title, plot=plot,
                             year=year, premiered=date, genre=genres or None,
                             rating=raw.get("vote_average") if type(raw.get("vote_average")) in (int, float) else None,
                             votes=raw.get("vote_count") if type(raw.get("vote_count")) is int else None, runtime=runtime,
                             season=raw.get("season_number") if type(raw.get("season_number")) is int else None,
                             episode=raw.get("episode_number") if type(raw.get("episode_number")) is int else None)
    if parent.get("name"):
        result["tvshowtitle"] = parent["name"]
    if raw.get("id"):
        result["uniqueid"] = {"tmdb": str(raw["id"])}
    return result


def show(nav, addon, core, params):
    client = TMDB(addon, core)
    action = params.get("action")
    try:
        if action in LIST_ROUTES:
            listing(nav, client, action, params)
        elif action == "tv_seasons":
            seasons(nav, client, params)
        elif action == "tv_episodes":
            episodes(nav, client, params)
        elif action == "catalogue_details":
            details(nav, client, params, addon)
        else:
            raise CatalogueError("Unknown catalogue page.")
    except CatalogueError as failure:
        xbmcgui.Dialog().ok("MDM Flix", str(failure))
        nav.add_action("Open TMDB settings", "open_settings")
        nav.end()


def listing(nav, client, action, params):
    media, kind = LIST_ROUTES[action]
    query = params.get("query", "")
    if kind == "search" and not query:
        keyboard = xbmc.Keyboard("", "Search Movies" if media == "movie" else "Search TV Shows")
        keyboard.doModal()
        if not keyboard.isConfirmed() or not keyboard.getText().strip():
            nav.end("movies" if media == "movie" else "tvshows")
            return
        query = keyboard.getText().strip()
    page = number(params.get("page", 1), 1, 500)
    data = client.listing(media, kind, page, query)
    count = 0
    for raw in data["results"]:
        if not isinstance(raw, dict) or raw.get("adult") is True:
            continue
        try:
            tmdb_id = number(raw.get("id"), 1)
        except CatalogueError:
            continue
        metadata = info(raw, "movie" if media == "movie" else "tvshow")
        nav.add_folder(metadata["title"], "catalogue_details" if media == "movie" else "tv_seasons",
                       params={"media_type": media, "tmdb_id": tmdb_id}, artwork=artwork(raw, addon=client.addon), info=metadata)
        count += 1
    if not count:
        xbmcgui.Dialog().notification("MDM Flix", "No results found.", xbmcgui.NOTIFICATION_INFO, 3000)
    total = data.get("total_pages", 1)
    total = min(total, 500) if type(total) is int and total > 0 else 1
    if page < total:
        nav.add_folder("Next page ({})".format(page + 1), action,
                       params={"page": page + 1, "query": query})
    nav.end("movies" if media == "movie" else "tvshows")


def seasons(nav, client, params):
    tmdb_id = number(params.get("tmdb_id"), 1)
    data = client.details("tv", tmdb_id)
    rows = data.get("seasons")
    if not isinstance(rows, list):
        raise CatalogueError("TMDB did not return season information. Please try again.")
    count = 0
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            season = number(raw.get("season_number"))
        except CatalogueError:
            continue
        metadata = info(raw, "season", data)
        name = raw.get("name")
        name = name if isinstance(name, str) and name else ("Specials" if season == 0 else "Season {}".format(season))
        nav.add_folder(name, "tv_episodes",
                       params={"tmdb_id": tmdb_id, "season": season}, artwork=artwork(raw, data, client.addon), info=metadata)
        count += 1
    if not count:
        xbmcgui.Dialog().notification("MDM Flix", "No seasons available.", xbmcgui.NOTIFICATION_INFO, 3000)
    nav.end("seasons")


def episodes(nav, client, params):
    tmdb_id = number(params.get("tmdb_id"), 1)
    season = number(params.get("season"))
    parent = client.details("tv", tmdb_id)
    data = client.season(tmdb_id, season)
    count = 0
    for raw in data["episodes"]:
        if not isinstance(raw, dict):
            continue
        try:
            episode = number(raw.get("episode_number"), 1)
        except CatalogueError:
            continue
        raw = dict(raw, season_number=season)
        metadata = info(raw, "episode", parent)
        nav.add_folder("{}. {}".format(episode, metadata["title"]), "catalogue_details",
                       params={"media_type": "tv", "tmdb_id": tmdb_id, "season": season, "episode": episode},
                       artwork=artwork(raw, parent, client.addon), info=metadata)
        count += 1
    if not count:
        xbmcgui.Dialog().notification("MDM Flix", "No episodes available.", xbmcgui.NOTIFICATION_INFO, 3000)
    nav.end("episodes")


def details(nav, client, params, addon):
    media = params.get("media_type", "movie")
    tmdb_id = number(params.get("tmdb_id"), 1)
    parent = None
    if media == "tv":
        season = number(params.get("season"))
        episode = number(params.get("episode"), 1)
        parent = client.details("tv", tmdb_id)
        data = client.request("tv/{}/season/{}/episode/{}".format(tmdb_id, season, episode), ttl=3600)
    else:
        data = client.details(media, tmdb_id)
    metadata = info(data, "episode" if media == "tv" else "movie", parent)
    text = metadata["plot"]
    if metadata.get("premiered"):
        text += "\n\nReleased: " + metadata["premiered"]
    if metadata.get("genre"):
        text += "\nGenres: " + ", ".join(metadata["genre"])
    if "rating" in metadata:
        text += "\nTMDB rating: {}".format(metadata["rating"])
    if metadata.get("duration"):
        text += "\nRuntime: {} minutes".format(int(metadata["duration"] / 60))
    text += "\n\nTMDB {} ID: {}".format("show" if media == "tv" else "movie", tmdb_id)
    if media == "tv":
        text += "\nSeason {} · Episode {}".format(season, episode)
    text += "\n\nPlayback: CocoScrapers sources resolved through your AllDebrid account."
    nav.add_action("View title information", "catalogue_info", params=dict(params), artwork=artwork(data, parent, addon), info=metadata)
    playback_params = {"media_type": media, "tmdb_id": tmdb_id}
    if media == "tv":
        playback_params.update(season=season, episode=episode)
    if addon.getSetting("playback_mode") == "Autoplay":
        nav.add_playable("Play (Autoplay)", "autoplay", params=playback_params, artwork=artwork(data, parent, addon), info=metadata)
    else:
        nav.add_folder("Find playback sources", "sources", params=playback_params, artwork=artwork(data, parent, addon), info=metadata)
    xbmcgui.Dialog().textviewer(metadata["title"], text)
    nav.end()
