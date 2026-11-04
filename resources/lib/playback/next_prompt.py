"""Session-only ownership for a Next Episode prompt after natural playback end."""
import json
import re

import xbmcgui

PROPERTY = 'MDM.Flix.NextPrompt'


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


def offer(token,item):
    value=dict(token=token,state='playing',**{key:item[key] for key in ('tmdb_id','season','episode')})
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
