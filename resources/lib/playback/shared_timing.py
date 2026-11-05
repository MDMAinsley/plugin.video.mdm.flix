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


def matched_timings(addon, file_id, item, duration, token=None):
    if not file_id:
        return {}
    from resources.lib.playback import shared_catalogue
    if shared_catalogue.enabled(addon):
        folder=Path(xbmcvfs.translatePath(addon.getAddonInfo('profile')))
        results={}
        conflicts=set()
        for name in ('native_cut_evidence.json','shared_cut_evidence.json'):
            native=name.startswith('native_')
            if native and (not token or addon.getSetting('episode_native_identity')=='false'):
                continue
            try:
                with (folder/name).open(encoding='utf8') as stream:
                    raw=stream.read(2049)
                evidence=json.loads(raw) if len(raw)<=2048 else {}
                if (evidence.get('schema')!=1 or evidence.get('file_id')!=file_id
                        or native and evidence.get('token')!=token
                        or any(evidence.get(key)!=item[key] for key in ('tmdb_id','season','episode'))
                        or number(evidence.get('duration'),60) is None or abs(evidence['duration']-duration)>2):
                    continue
                result=shared_catalogue.match(addon,item,duration,evidence.get('anchors'))
                for kind,row in result.items():
                    if kind in results and any(results[kind].get(key)!=row.get(key) for key in ('marker_id','revision','start','end','tier')):
                        conflicts.add(kind)
                    else:
                        results[kind]=row
            except (OSError,ValueError,TypeError,KeyError,AttributeError):
                continue
        results={kind:row for kind,row in results.items() if kind not in conflicts}
        if results:
            return results
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
            if tier in ('trusted reviewer','community reviewed') and shared_catalogue.cached(addon) is not None:
                continue
            if bounds and tier in ('trusted reviewer', 'community reviewed', 'software generated'):
                matches[kind] = dict(kind=kind,start=bounds[0],end=bounds[1],range=bounds, provider='Shared timing · ' + tier,
                                     tier=tier, marker_id=row.get('id'), revision=row.get('revision'),
                                     unverified=tier == 'software generated', online=False)
        return matches
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}
