"""Quiet, bounded home rows. No playback/provider calls or pagination."""
from resources.lib.catalogue.tmdb import TMDB, CatalogueError, number
from resources.lib.catalogue.browse import info, artwork


def show(nav, addon, core, params):
    media = params.get("media_type", "movie")
    if media not in ("movie", "tv"):
        nav.end()
        return
    client = TMDB(addon, core)
    if not client.configured or core is None:
        nav.end("movies" if media == "movie" else "tvshows")
        return
    try:
        data = client.listing(media, "trending", 1)
        count = 0
        # Limit raw processing as well as rendered entries, even if a fixture/API
        # returns an unexpectedly huge page. The TMDB request uses Core's cache.
        for raw in data["results"][:40]:
            if not isinstance(raw, dict) or raw.get("adult") is True:
                continue
            try:
                identifier = number(raw.get("id"), 1)
            except CatalogueError:
                continue
            metadata = info(raw, "movie" if media == "movie" else "tvshow")
            nav.add_folder(metadata["title"], "catalogue_details" if media == "movie" else "tv_seasons",
                params={"media_type": media, "tmdb_id": identifier},
                artwork=artwork(raw, addon=addon), info=metadata)
            count += 1
            if count == 12:
                break
    except CatalogueError:
        pass  # Empty row; home settings/navigation remains available, no modal.
    nav.end("movies" if media == "movie" else "tvshows")
