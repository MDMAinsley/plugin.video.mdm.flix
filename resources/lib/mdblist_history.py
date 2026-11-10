"""MDBList's watched snapshot and per-item write/readback contract."""
from datetime import datetime, timezone
import time

from .mdblist_client import MDBError
from .mdblist_import import object_field, title
from .playback.progress import ProgressError, clean, key


def timestamp(value):
    try:
        moment = datetime.fromisoformat(value.replace('Z','+00:00'))
        if moment.tzinfo is not None:
            result = int(moment.timestamp())
            if 0 < result <= time.time()+60:
                return result
    except (AttributeError, ValueError, OverflowError, OSError):
        pass
    return 0


def recent_watched(client):
    records, seen = {}, set()
    cursor = ''
    complete = True
    for _ in range(4):
        query = {'limit': 300}
        if cursor:
            query['cursor'] = cursor
        page = client.call('GET','/sync/watched',query=query)
        if not isinstance(page,dict) or any(not isinstance(page.get(kind),list) for kind in ('movies','episodes')):
            raise MDBError('invalid_response')
        for kind in ('movie','episode'):
            for row in page[kind+'s']:
                if not isinstance(row,dict):
                    complete = False
                    continue
                data = object_field(row,kind)
                changed = timestamp(row.get('last_watched_at') or row.get('watched_at'))
                if not changed:
                    complete = False
                    continue
                if kind == 'episode':
                    show = object_field(data,'show') or object_field(row,'show')
                    show_title = title(show.get('title')) or 'TV'
                    item = dict(media_type=kind,tmdb_id=object_field(show,'ids').get('tmdb'),
                                episode_tmdb_id=object_field(data,'ids').get('tmdb'),season=data.get('season'),
                                episode=data.get('number'),title=title(data.get('name') or data.get('title')) or show_title,
                                tvshowtitle=show_title)
                else:
                    item = dict(media_type=kind,tmdb_id=object_field(data,'ids').get('tmdb'),title=title(data.get('title')) or 'Film')
                try:
                    item = clean(item)
                    identity = key(item)
                except ProgressError:
                    complete = False
                    continue
                if identity not in records or changed > records[identity][1]:
                    records[identity] = item, changed
        paging = object_field(page,'pagination')
        cursor = paging.get('next_cursor')
        if not cursor and not paging.get('has_more'):
            return list(records.values()), complete
        if not isinstance(cursor,str) or not 0 < len(cursor) <= 2048 or cursor in seen:
            raise MDBError('invalid_response')
        seen.add(cursor)
    return list(records.values()), False


def item_state(client, item, identifier):
    data = client.call('POST','/sync/state/{}/tmdb'.format(item['media_type']),{'ids':[identifier]})
    if not isinstance(data,dict) or not isinstance(data.get('items'),list):
        raise MDBError('invalid_response')
    for row in data['items']:
        if isinstance(row,dict) and str(row.get('id')) == str(identifier) and type(row.get('watched')) is bool:
            changed = timestamp(row.get('last_watched_at'))
            if row['watched'] and not changed:
                raise MDBError('invalid_response')
            return changed if row['watched'] else 0
    raise MDBError('title_not_found')


def watched_body(item, identifier, changed=None):
    entry = {'ids':{'tmdb':identifier}}
    if changed:
        entry['watched_at'] = datetime.fromtimestamp(int(changed),timezone.utc).isoformat()
    return {item['media_type']+'s':[entry]}
