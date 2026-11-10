"""Validate MDBList rows before handing them to the local stores."""
import math
import time

from .library_store import LibraryError, MAX_TITLES, identity
from .mdblist_client import MDBError
from .playback.progress import MAX_RECORDS, ProgressError, clean, key


def title(value):
    if not isinstance(value, str):
        return ''
    return ''.join(char for char in value[:200] if char.isprintable()).strip()


def object_field(row, field):
    value = row.get(field)
    return value if isinstance(value, dict) else {}


def watchlist_page(client, cursor='', limit=50):
    if len(cursor) > 2048:
        raise MDBError('invalid_request')
    query = {'limit': limit}
    if cursor:
        query['cursor'] = cursor
    data = client.call('GET', '/watchlist/items', query=query)
    buckets = ('movies', 'shows', 'seasons', 'episodes')
    if (not isinstance(data, dict) or not any(name in data for name in buckets)
            or any(not isinstance(data.get(name, []), list) for name in buckets)):
        raise MDBError('invalid_response')
    rows = []
    for bucket, media in (('movies', 'movie'), ('shows', 'tv')):
        for row in data.get(bucket, []):
            if not isinstance(row, dict) or row.get('adult') in (True, '1'):
                continue
            name = title(row.get('title'))
            if not name:
                continue
            try:
                _, identifier = identity(media, object_field(row, 'ids').get('tmdb', row.get('id')))
            except LibraryError:
                continue
            rows.append(dict(media=media, tmdb_id=identifier, title=name, date='', plot='', poster='', backdrop=''))
    paging = object_field(data, 'pagination')
    next_cursor = data.get('next_cursor') or paging.get('next_cursor')
    if next_cursor and (not isinstance(next_cursor, str) or len(next_cursor) > 2048 or next_cursor == cursor):
        raise MDBError('invalid_response')
    if data.get('_has_more') and not next_cursor:
        raise MDBError('invalid_response')
    return rows, next_cursor or ''


def watchlist_titles(client, cancelled):
    titles, cursors = {}, {''}
    cursor = ''
    for _ in range(6):
        if cancelled():
            return []
        rows, cursor = watchlist_page(client, cursor, limit=100)
        for row in rows:
            titles.setdefault((row['media'], row['tmdb_id']), row)
        if len(titles) > MAX_TITLES:
            break
        if not cursor:
            return list(titles.values())
        if cursor in cursors:
            raise MDBError('invalid_response')
        cursors.add(cursor)
    raise MDBError('watchlist_too_large')


def paused_records(client):
    data = client.playback()
    if not isinstance(data, list):
        raise MDBError('invalid_response')
    if len(data) > MAX_RECORDS:
        raise MDBError('progress_too_large')
    records = {}
    newest_allowed = time.time() + 60
    for row in data:
        if not isinstance(row, dict):
            continue
        runtime, percentage, updated = (row.get(field) for field in ('runtime', 'progress', 'updated_at_ts'))
        if (type(runtime) is not int or not 0 < runtime <= 1440
                or type(percentage) not in (int, float) or not 0 < percentage < 80
                or not math.isfinite(percentage)
                or type(updated) is not int or not 0 < updated <= newest_allowed):
            continue
        duration = runtime * 60
        position = duration * percentage / 100
        if position < 30:
            continue
        media = row.get('type')
        if media == 'movie':
            movie = object_field(row, 'movie')
            item = dict(media_type=media, tmdb_id=object_field(movie, 'ids').get('tmdb'),
                        title=title(movie.get('title')))
        elif media == 'episode':
            show, episode = object_field(row, 'show'), object_field(row, 'episode')
            show_title = title(show.get('title'))
            item = dict(media_type=media, tmdb_id=object_field(show, 'ids').get('tmdb'),
                        season=episode.get('season'), episode=episode.get('number'),
                        title=title(episode.get('title')) or show_title, tvshowtitle=show_title)
        else:
            continue
        try:
            item = clean(item)
            identifier = key(item)
        except ProgressError:
            continue
        if identifier not in records or updated > records[identifier][3]:
            records[identifier] = item, position, duration, updated
    return list(records.values())
