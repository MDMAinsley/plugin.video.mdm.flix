"""Atomic expiring sessions. Opaque IDs; no resolved URL persistence."""
import json
import os
import tempfile
import time
import uuid
import xbmcaddon
import xbmcvfs
from resources.lib.constants import ADDON_ID
from resources.lib.playback.errors import PlaybackError
SESSION_FILE='sources_session.json'
TTL=1800


def _session_path():
    path=xbmcvfs.translatePath(xbmcaddon.Addon(ADDON_ID).getAddonInfo('profile'))
    os.makedirs(path,exist_ok=True)
    return os.path.join(path,SESSION_FILE)


def clear_sources():
    try: os.remove(_session_path())
    except OSError: pass


def store_sources(sources):
    data={}
    for source in sources or []:
        if not isinstance(source,dict): continue
        source_id=uuid.uuid4().hex
        data[source_id]=dict(source,source_id=source_id)
    payload={'schema':2,'created':int(time.time()),'sources':data}
    temporary=None
    try:
        encoded=json.dumps(payload,ensure_ascii=False)
        path=_session_path()
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=os.path.dirname(path),prefix='.mdm-sources-',delete=False) as stream:
            temporary=stream.name; stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
    except Exception:
        raise PlaybackError('Source results could not be saved. Check Kodi storage and search again.') from None
    finally:
        if temporary and os.path.exists(temporary):
            try: os.remove(temporary)
            except OSError: pass
    return data


def get_source(source_id):
    if not isinstance(source_id,str) or len(source_id)!=32: return None
    try:
        with open(_session_path(),encoding='utf-8') as stream: payload=json.load(stream)
        if not isinstance(payload,dict) or payload.get('schema')!=2: return None
        created=payload.get('created'); now=int(time.time())
        if type(created) is not int or created>now or now-created>=TTL: return None
        rows=payload.get('sources'); source=rows.get(source_id) if isinstance(rows,dict) else None
        return source if isinstance(source,dict) else None
    except Exception: return None
