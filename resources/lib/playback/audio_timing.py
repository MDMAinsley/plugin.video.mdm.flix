"""Local audio suggestions, bound to the resolved file and episode."""
import hashlib
import json
import tempfile
from pathlib import Path

import xbmcvfs

from resources.lib.playback import timing_rules as rules


def file_digest(player):
    try:
        address = player.getPlayingFile()
        return hashlib.sha256(address.encode('utf8')).hexdigest() if address else None
    except (RuntimeError, AttributeError):
        return None


def confirmation_key(digest, item):
    if not digest:
        return None
    identity = [digest, item['tmdb_id'], item['season'], item['episode']]
    return hashlib.sha256(json.dumps(identity).encode('utf8')).hexdigest()


def saved_suggestion(addon, item):
    path = Path(xbmcvfs.translatePath(addon.getAddonInfo('profile'))) / 'audio_intro_candidate.json'
    try:
        with path.open(encoding='utf8') as stream:
            value = json.loads(stream.read(8193))
        if not isinstance(value, dict) or value.get('schema') != 1:
            return None
        if any(value.get(k) != item[k] for k in ('tmdb_id', 'season', 'episode')):
            return None
        row = dict(kind='intro', start=value.get('start'), end=value.get('end'), provider='Audio match')
        return dict(row, file_id=value.get('file_id')) if rules.interval(row, 86400) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def suggestion(addon, digest, item, duration):
    row = saved_suggestion(addon, item)
    if digest and row and row['file_id'] == digest and rules.interval(row, duration):
        return row
    return None

def write_search_hint(addon, digest, item, duration, rows, previous):
    """Publish a bounded search hint. This never enters the playback decision."""
    if not digest:
        return previous
    candidates = []
    for row in rows:
        if row.get('kind') != 'intro':
            continue
        bounds = rules.interval(row, duration)
        if not bounds or bounds[0] > 600 or bounds[1] - bounds[0] > 120:
            continue
        runtime = rules.number(row.get('runtime'), 60)
        candidates.append(((runtime is None, abs(runtime - duration) if runtime else 0,
                            row.get('pinned') is not True, bounds), bounds))
    if not candidates:
        return previous
    _, bounds = min(candidates)
    signature = (digest, *bounds)
    if signature == previous:
        return previous
    path = Path(xbmcvfs.translatePath(addon.getAddonInfo('profile'))) / 'audio_search_hint.json'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=path.parent,
                                         prefix='.audio-hint-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(dict(schema=1, file_id=digest, tmdb_id=item['tmdb_id'],
                           season=item['season'], episode=item['episode'],
                           start=bounds[0], end=bounds[1]), stream)
        temporary.replace(path)
        return signature
    except OSError:
        return previous
    finally:
        if temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
