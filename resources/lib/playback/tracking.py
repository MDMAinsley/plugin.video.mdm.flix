"""Pass a source's catalogue identity to the actual Kodi ListItem only at handoff."""
import json
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
import xbmcgui
from resources.lib.playback.progress import Store,clean,ProgressError
from resources.lib.playback.errors import Cancelled

PROPERTY='mdm.flix.progress'
_source=ContextVar('mdm_flix_source',default=None)

@contextmanager
def source(row,addon):
    token=_source.set((row,addon))
    try:yield
    finally:_source.reset(token)

def stamp(listitem):
    current=_source.get()
    if not current:return
    row,addon=current
    if addon.getSetting('progress_enabled')=='false' and not any(addon.getSetting(name)=='true' for name in ('episode_next_enabled','episode_intro_enabled')):return
    try:
        item=clean(row.get('extra',{}).get('item'))
    except ProgressError:
        return
    resume=0
    try:
        previous=None if addon.getSetting('progress_enabled')=='false' else Store(addon).get(item)
    except ProgressError as error:
        xbmcgui.Dialog().notification('MDM Flix',str(error));previous=None
    if previous and not previous['watched'] and previous['position']>=30:
        at=int(previous['position'])
        mode=row.get('_progress_mode')
        choice=0 if mode=='resume' else 1 if mode=='restart' else xbmcgui.Dialog().select('Continue watching?', ['Resume from {}:{:02d}'.format(at//60,at%60),'Start again'])
        if choice<0:raise Cancelled('Resume cancelled.')
        if choice==0:resume=at
    payload=dict(schema=1,token=uuid.uuid4().hex,created=int(time.time()),item=item,resume=resume)
    from resources.lib.playback.chapter_facts import fingerprint
    chapter_key=fingerprint(row)
    if chapter_key:payload['chapter_key']=chapter_key
    listitem.setProperty(PROPERTY,json.dumps(payload,ensure_ascii=False))

def read(listitem):
    try:
        raw=listitem.getProperty(PROPERTY)
        if not isinstance(raw,str) or len(raw)>8192:return None
        value=json.loads(raw)
        if not isinstance(value,dict) or value.get('schema')!=1:return None
        if not isinstance(value.get('token'),str) or not re.fullmatch('[0-9a-f]{32}',value['token']):return None
        now=int(time.time());created=value.get('created');resume=value.get('resume')
        if type(created) is not int or not 0<=now-created<=300:return None
        if type(resume) is not int or not 0<=resume<=86400:return None
        result=dict(token=value['token'],item=clean(value.get('item')),resume=resume)
        chapter_key=value.get('chapter_key')
        if isinstance(chapter_key,str) and re.fullmatch('[0-9a-f]{64}',chapter_key):result['chapter_key']=chapter_key
        return result
    except (ValueError,TypeError,ProgressError):return None
