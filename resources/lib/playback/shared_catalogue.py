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
from resources.lib.playback.cut_evidence import normalize, groups, AUDIO

URL = 'https://raw.githubusercontent.com/MDMAinsley/mdm-timing-catalogue/main/playback-snapshot-v3.json'
MAX_BYTES = 2_000_000
METHOD = 'chromaprint2-fixed-32-v1'
TIERS = ('trusted reviewer', 'community reviewed', 'software generated')
HEX = re.compile('[0-9a-f]{64}')
_cached = None


def path(addon):
    return Path(xbmcvfs.translatePath(addon.getAddonInfo('profile'))) / 'shared_catalogue_v3.json'


def enabled(addon):
    return addon.getSetting('episode_timing_lookup') != 'false' and addon.getSetting('episode_shared_catalogue') != 'false'


def anchors(value):
    return set(normalize(value))


def validate(data):
    if not isinstance(data, dict) or set(data) != {'schema', 'cuts'} or type(data['schema']) is not int or data['schema'] not in (2,3):
        raise ValueError('Unsupported shared catalogue')
    cuts = data['cuts']
    if not isinstance(cuts, dict) or len(cuts) > 4000:
        raise ValueError('Invalid cut list')
    for key, cut in cuts.items():
        if not HEX.fullmatch(key) or not isinstance(cut, dict) or set(cut) != ({'episode', 'duration', 'anchors', 'markers'} if data['schema']==2 else {'episode','duration','identities','markers'}):
            raise ValueError('Invalid cut fields')
        episode = cut['episode']
        if (not isinstance(episode, list) or len(episode) != 3
                or any(type(part) is not int for part in episode)
                or episode[0] < 1 or episode[1] < 0 or episode[2] < 1
                or rules.number(cut['duration'], 60) is None):
            raise ValueError('Invalid cut identity')
        if data['schema']==2:
            if normalize(cut['anchors'])[0][0]!=AUDIO:
                raise ValueError('Unsupported legacy evidence')
        else:
            groups(cut['identities'])
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
    cache=path(addon)
    for actual in (cache,cache.with_name('shared_catalogue.json')):
        try:
            stat=actual.stat()
            signature=(str(actual),stat.st_mtime_ns,stat.st_size)
            if _cached and _cached[0]==signature:
                return _cached[1]
            data=read(actual)
            _cached=(signature,data)
            return data
        except (OSError,ValueError,TypeError,KeyError):
            continue
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


def refresh(addon, transport=download, force=False):
    """Run only in the timing worker. Preserve the old file on any failure."""
    if not enabled(addon):
        return 'Disabled'
    cache = path(addon)
    previous = cached(addon)
    retry = cache.with_suffix('.attempt')
    temporary = None
    try:
        now = time.time()
        if not force and previous is not None and cache.exists() and -5 <= now - cache.stat().st_mtime < 86400:
            return 'Cached'
        if not force and retry.exists() and -5 <= now - retry.stat().st_mtime < 900:
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
                  and any(set(group)==observed for group in (groups(cut['identities']) if data['schema']==3 else (normalize(cut['anchors']),)))]
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
