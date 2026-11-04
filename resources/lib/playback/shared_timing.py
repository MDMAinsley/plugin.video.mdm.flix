"""Read a local cut match produced by the catalogue helper."""
import json
import os
import tempfile
from pathlib import Path

import xbmcvfs

from resources.lib.playback.timing_rules import interval, number


def request_match(addon, file_id, item):
    """Signal the opt-in companion once per resolved playback file."""
    if not file_id:
        return
    folder = Path(xbmcvfs.translatePath(addon.getAddonInfo('profile')))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=folder,
                                         delete=False) as stream:
            temporary = stream.name
            json.dump(dict(schema=1, file_id=file_id, tmdb_id=item['tmdb_id'],
                           season=item['season'], episode=item['episode']), stream)
        os.replace(temporary, folder / 'shared_timing_request.json')
        temporary = None
    except OSError:
        pass
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def matched_timings(addon, file_id, item, duration):
    if not file_id:
        return {}
    path = Path(xbmcvfs.translatePath(addon.getAddonInfo('profile'))) / 'shared_timing_match.json'
    try:
        with path.open(encoding='utf8') as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            return {}
        data = json.loads(raw)
        if data['schema'] != 1 or data['file_id'] != file_id:
            return {}
        if any(data[key] != item[key] for key in ('tmdb_id', 'season', 'episode')):
            return {}
        runtime = number(data['duration'], 1)
        if runtime is None or abs(runtime - duration) > 2:
            return {}
        matches = {}
        for kind in ('intro', 'outro'):
            row = data['markers'].get(kind, {})
            bounds = interval(dict(row, kind=kind), duration)
            tier = row.get('tier')
            if bounds and tier in ('trusted reviewer', 'community reviewed', 'software generated'):
                matches[kind] = dict(kind=kind,start=bounds[0],end=bounds[1],range=bounds, provider='Shared timing · ' + tier,
                                     tier=tier, marker_id=row.get('id'), revision=row.get('revision'),
                                     unverified=tier == 'software generated', online=False)
        return matches
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}
