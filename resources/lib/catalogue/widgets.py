"""Quiet, bounded home rows. No playback/provider calls or pagination."""
from urllib.parse import urlencode
from resources.lib.catalogue.tmdb import TMDB, CatalogueError, number
from resources.lib.catalogue.browse import info, artwork

ROW_LIMIT = 12


def title_link(**identity):
    return {'mdm_home_title': 'plugin://plugin.video.mdm.flix/?' + urlencode(dict(identity, action='home_title'))}


def show_continue(nav, addon):
    from resources.lib.playback.progress import ProgressError, display_position
    from resources.lib.playback.progress_ui import identity_params, label, play_entry, title_metadata
    from resources.lib.playback.viewing import Viewing

    if addon.getSetting('progress_enabled') != 'false':
        try:
            for row in Viewing(addon).rows()[:ROW_LIMIT]:
                item = row['item']
                text = label(item) + ' · ' + display_position(row['position'])
                play_entry(nav, addon, text, item, 'resume', properties=title_link(**identity_params(item)),
                           **title_metadata(addon, None, item, row))
        except ProgressError:
            pass
    nav.end('videos', cache=False)


def show_home_list(nav, addon):
    from resources.lib.catalogue.cards import add_title
    from resources.lib.library_store import Library, LibraryError
    from resources.lib.library_ui import card_metadata

    try:
        library = Library(addon)
        for row in library.rows(library.home_list()['id'], limit=ROW_LIMIT):
            add_title(nav, addon, row['title'], row['media'], row['tmdb_id'],
                      properties=title_link(media_type=row['media'], tmdb_id=row['tmdb_id']),
                      **card_metadata(row, addon))
    except (LibraryError, CatalogueError):
        pass
    nav.end('videos', cache=False)


def show(nav, addon, core, params):
    row = params.get('row')
    if row == 'continue':
        return show_continue(nav, addon)
    if row == 'my_list':
        return show_home_list(nav, addon)

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
            from resources.lib.catalogue.cards import add_title
            add_title(nav, addon, metadata["title"], media, identifier,
                      artwork=artwork(raw, addon=addon), info=metadata,
                      properties=title_link(media_type=media, tmdb_id=identifier))
            count += 1
            if count == ROW_LIMIT:
                break
    except CatalogueError:
        pass  # Empty row; home settings/navigation remains available, no modal.
    nav.end("movies" if media == "movie" else "tvshows")
