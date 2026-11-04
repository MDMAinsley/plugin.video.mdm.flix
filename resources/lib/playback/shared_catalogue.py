"""Kodi-native snapshot cache and exact-cut lookup; decoding is separate."""
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.request

import xbmcvfs

from resources.lib.playback import timing_rules as rules

URL = 'https://raw.githubusercontent.com/MDMAinsley/mdm-timing-catalogue/main/playback-snapshot.json'
MAX_BYTES = 2_000_000
METHOD = 'chromaprint2-fixed-32-v1'
TIERS = ('trusted reviewer', 'community reviewed', 'software generated')
HEX = re.compile('[0-9a-f]{64}')
_cached = None


def path(addon):
    return Path(xbmcvfs.translatePath(addon.getAddonInfo('profile'))) / 'shared_catalogue.json'


def enabled(addon):
    return addon.getSetting('episode_timing_lookup') != 'false' and addon.getSetting('episode_shared_catalogue') != 'false'


def anchors(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('Invalid cut anchors')
    result = []
    for anchor in value:
        if (not isinstance(anchor, list) or len(anchor) != 3 or anchor[0] != METHOD
                or type(anchor[1]) is not int or anchor[1] not in (0, 16)
                or not isinstance(anchor[2], str) or not HEX.fullmatch(anchor[2])):
            raise ValueError('Invalid cut anchor')
        result.append(tuple(anchor))
    if {row[1] for row in result} != {0, 16}:
        raise ValueError('Incomplete cut anchors')
    return set(result)


def validate(data):
    if not isinstance(data, dict) or set(data) != {'schema', 'cuts'} or type(data['schema']) is not int or data['schema'] != 2:
        raise ValueError('Unsupported shared catalogue')
    cuts = data['cuts']
    if not isinstance(cuts, dict) or len(cuts) > 4000:
        raise ValueError('Invalid cut list')
    for key, cut in cuts.items():
        if not HEX.fullmatch(key) or not isinstance(cut, dict) or set(cut) != {'episode', 'duration', 'anchors', 'markers'}:
            raise ValueError('Invalid cut fields')
        episode = cut['episode']
        if (not isinstance(episode, list) or len(episode) != 3
                or any(type(part) is not int for part in episode)
                or episode[0] < 1 or episode[1] < 0 or episode[2] < 1
                or rules.number(cut['duration'], 60) is None):
            raise ValueError('Invalid cut identity')
        anchors(cut['anchors'])
        markers = cut['markers']
        if not isinstance(markers, dict) or any(kind not in ('intro', 'outro') for kind in markers):
            raise ValueError('Invalid markers')
        for kind, marker in markers.items():
            if (not isinstance(marker, dict) or set(marker) != {'id', 'revision', 'start', 'end', 'tier'}
                    or not isinstance(marker['id'], str) or not HEX.fullmatch(marker['id'])
                    or type(marker['revision']) is not int or marker['revision'] < 1
                    or marker['tier'] not in TIERS
                    or not rules.interval(dict(marker, kind=kind), cut['duration'])):
                raise ValueError('Invalid marker')
    return data


def read(cache):
    with cache.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Shared catalogue too large')
    return validate(json.loads(raw))


def cached(addon):
    global _cached
    cache = path(addon)
    try:
        stat = cache.stat()
        signature = (str(cache), stat.st_mtime_ns, stat.st_size)
        if _cached and _cached[0] == signature:
            return _cached[1]
        data = read(cache)
        _cached = (signature, data)
        return data
    except (OSError, ValueError, TypeError, KeyError):
        return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def download():
    request = urllib.request.Request(URL, headers={'Accept': 'application/json', 'User-Agent': 'MDM-Flix-Catalogue/1'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=5) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Shared catalogue too large')
    validate(json.loads(raw))
    return raw


def refresh(addon, transport=download):
    """Run only in the timing worker. Preserve the old file on any failure."""
    if not enabled(addon):
        return 'Disabled'
    cache = path(addon)
    previous = cached(addon)
    retry = cache.with_suffix('.attempt')
    temporary = None
    try:
        now = time.time()
        if previous is not None and -5 <= now - cache.stat().st_mtime < 86400:
            return 'Cached'
        if retry.exists() and -5 <= now - retry.stat().st_mtime < 900:
            return 'Offline cache' if previous is not None else 'Retry wait'
        cache.parent.mkdir(parents=True, exist_ok=True)
        retry.touch()
        raw = transport()
        if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
            raise ValueError('Invalid catalogue response')
        validate(json.loads(raw))
        if not enabled(addon):
            return 'Disabled'
        with tempfile.NamedTemporaryFile(dir=cache.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        os.replace(temporary, cache)
        return 'Updated'
    except (OSError, ValueError, TypeError, KeyError):
        return 'Offline cache' if previous is not None else 'Unavailable'
    finally:
        if temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def match(addon, item, duration, evidence):
    if not enabled(addon) or rules.number(duration, 60) is None:
        return {}
    try:
        observed = anchors(evidence)
    except (ValueError, TypeError):
        return {}
    data = cached(addon)
    if data is None:
        return {}
    episode = [item[key] for key in ('tmdb_id', 'season', 'episode')]
    candidates = [cut for cut in data['cuts'].values()
                  if cut['episode'] == episode and abs(cut['duration'] - duration) <= 3
                  and anchors(cut['anchors']) == observed]
    if len(candidates) != 1:
        return {}
    result = {}
    for kind, marker in candidates[0]['markers'].items():
        bounds = rules.interval(dict(marker, kind=kind), duration)
        if bounds:
            result[kind] = dict(kind=kind, start=bounds[0], end=bounds[1], range=bounds,
                marker_id=marker['id'], revision=marker['revision'], tier=marker['tier'],
                provider='Shared timing · '+marker['tier'],
                unverified=marker['tier']=='software generated', online=True)
    return result
