"""Session-only ownership for a Next Episode prompt after natural playback end."""
import json
import re
import time
from uuid import uuid4

import xbmcgui

PROPERTY = 'MDM.Flix.NextPrompt'
CHAIN = 'MDM.Flix.EpisodeChain'
COUNTDOWN = 10
CHECK_AFTER = 5
EPISODE_KEYS = ('tmdb_id', 'season', 'episode')


def _chain():
    try:
        raw = xbmcgui.Window(10000).getProperty(CHAIN)
        value = json.loads(raw) if raw and len(raw) <= 512 else None
        return value if isinstance(value, dict) else {}
    except (AttributeError, RuntimeError, ValueError):
        return {}


def clear_chain(nonce=None):
    try:
        if nonce is None or _chain().get('nonce') == nonce:
            xbmcgui.Window(10000).clearProperty(CHAIN)
    except (AttributeError, RuntimeError):
        pass


def queue(item, count, unattended):
    nonce = uuid4().hex
    try:
        xbmcgui.Window(10000).setProperty(CHAIN, json.dumps(dict(
            nonce=nonce, expires=time.time()+240, count=count, unattended=unattended,
            item=[item[key] for key in EPISODE_KEYS])))
        return nonce
    except (AttributeError, RuntimeError):
        return None


def take(candidate):
    pending = _chain()
    nonce = candidate.get('episode_chain')
    if not nonce or pending.get('nonce') != nonce:
        if pending:clear_chain(pending.get('nonce'))
        return 0, False
    clear_chain(nonce)
    if (pending.get('expires', 0) >= time.time()
            and pending.get('item') == [candidate['item'][key] for key in EPISODE_KEYS]):
        count=pending.get('count')
        if type(count) is int and 0<=count<=CHECK_AFTER:
            return count,pending.get('unattended') is True
    return 0, False


def read():
    try:
        raw=xbmcgui.Window(10000).getProperty(PROPERTY)
        value=json.loads(raw) if raw and len(raw)<=1024 else None
        if (isinstance(value,dict) and value.get('state') in ('playing','ended')
                and isinstance(value.get('token'),str) and re.fullmatch('[0-9a-f]{32}',value['token'])
                and all(type(value.get(key)) is int for key in ('tmdb_id','season','episode'))
                and value['tmdb_id']>0 and value['season']>=0 and value['episode']>0):
            return value
    except (AttributeError,RuntimeError,ValueError):
        pass
    return None


def clear():
    try:xbmcgui.Window(10000).clearProperty(PROPERTY)
    except (AttributeError,RuntimeError):pass


def offer(token,item,target=None):
    value=dict(token=token,state='playing',**{key:item[key] for key in ('tmdb_id','season','episode')})
    if target:
        value['target']={key:target[key] for key in EPISODE_KEYS}
    try:
        xbmcgui.Window(10000).setProperty(PROPERTY,json.dumps(value))
    except (AttributeError,RuntimeError):
        pass


def ended():
    value=read()
    if value:
        value['state']='ended'
        try:xbmcgui.Window(10000).setProperty(PROPERTY,json.dumps(value))
        except (AttributeError,RuntimeError):pass


def owns(player,token,item):
    value=read()
    try:
        return bool(value and value['state']=='ended' and value['token']==token
                    and not player.isPlayingVideo()
                    and all(str(value[key])==str(item.get(key)) for key in ('tmdb_id','season','episode')))
    except (AttributeError,RuntimeError):
        return False
