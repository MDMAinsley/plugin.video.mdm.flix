"""Bounded on-demand public timing lookup for a measured candidate pool."""
import time
from resources.lib.playback import timing_rules as r,timing_service as s
from resources.lib.playback.timing_store import Store,TimingError

class Lookup:
    def __init__(self,addon,item,deadline,cancel=lambda:False,fetch=None):
        self.addon=addon;self.item=r.identity(item) or r.clean_identity(item);self.deadline=deadline;self.cancel=cancel
        self.fetch=fetch or (lambda provider,query,seconds:s.fetch(provider,query,timeout=seconds))
        self.store=Store(addon);self.rows=[];self.status=[];self.calls=0;self.durations=set();self.absent=False
    def read(self):
        try:self.rows,self.status=self.store.data(self.item)
        except TimingError:self.rows=[];self.status=['Timing cache unavailable']
        return self.rows
    def call(self,provider,query):
        if not s.enabled(self.addon) or self.cancel() or self.calls>=5 or time.monotonic()>=self.deadline-.1:return False,None
        try:
            if not self.store.reserve(provider):return False,None
            self.calls+=1
            return True,self.fetch(provider,query,min(2,max(.1,self.deadline-time.monotonic())))
        except s.FetchError as error:
            try:self.store.backoff(provider,error.delay)
            except TimingError:pass
        except (TimingError,OSError,ValueError,TypeError):pass
        return False,None
    def save(self,provider,rows,status=None):
        try:self.store.save(self.item,provider,rows,status or ('Ready' if rows else 'No usable timing data'),7*86400 if rows else 86400)
        except TimingError:pass
    def prime(self):
        if not self.item:return []
        self.read()
        if not s.enabled(self.addon):self.rows=[];return []
        for provider in ('IntroDB','TheIntroDB'):
            fresh=any(value.startswith(provider+': ') and not value.endswith('expired') for value in self.status)
            if fresh:
                if provider=='TheIntroDB':self.absent=provider+': No episode data' in self.status
                continue
            query={k:self.item[k] for k in ('imdb_id','season','episode')} if provider=='IntroDB' and self.item.get('imdb_id') else r.tidb_query(self.item)
            if provider=='IntroDB' and not self.item.get('imdb_id'):continue
            if provider=='TheIntroDB':query['list_versions']='true'
            ok,body=self.call(provider,query)
            if not ok:continue
            if body is None:
                self.save(provider,[],'No episode data' if provider=='TheIntroDB' else None)
                if provider=='TheIntroDB':self.absent=True
                continue
            if not isinstance(body,dict):continue
            rows=r.parse_introdb(body,self.item) if provider=='IntroDB' else r.parse_tidb(body,self.item)
            # A malformed/wrong-episode response must not overwrite a good cache.
            if provider=='TheIntroDB' and not r.tidb_identity(body,self.item):continue
            if provider=='IntroDB' and (body.get('imdb_id')!=self.item.get('imdb_id') or body.get('season')!=self.item['season'] or body.get('episode')!=self.item['episode']):continue
            self.save(provider,rows,'Versions available' if provider=='TheIntroDB' and not rows and r.versions(body,self.item) else None)
        return self.read()
    def measured(self,duration):
        self.read()
        if not s.enabled(self.addon):self.rows=[];return []
        duration=r.number(duration,60)
        if not duration or self.absent or not self.item:return self.rows
        if any(row.get('provider')=='TheIntroDB' and r.number(row.get('runtime'),60) and abs(row['runtime']-duration)<=5 for row in self.rows):return self.rows
        hint=round(duration)
        if hint in self.durations:return self.rows
        self.durations.add(hint)
        ok,body=self.call('TheIntroDB',dict(r.tidb_query(self.item),duration_ms=round(duration*1000)))
        if ok and body is not None and r.tidb_identity(body,self.item):
            new=r.parse_tidb(body,self.item);others=[row for row in self.rows if row.get('provider')=='TheIntroDB' and not any(row.get('runtime')==entry.get('runtime') for entry in new)]
            if new:self.save('TheIntroDB',(new+others)[:60])
        return self.read()
