"""Public timing requests run only in a separate bounded worker, never in tick."""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from resources.lib.playback import timing_rules as rules
from resources.lib.playback.timing_store import Store,TimingError

ENDPOINTS={'TheIntroDB':'https://api.theintrodb.org/v4/media','IntroDB':'https://api.introdb.app/segments'}


class FetchError(Exception):
    def __init__(self,status='Unavailable',delay=120):self.status=status;self.delay=delay;super().__init__(status)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def fetch(provider,query):
    url=ENDPOINTS[provider]+'?'+urllib.parse.urlencode(query)
    req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'MDM-Flix-Timings/0.12.0'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=4) as response:
            raw=response.read(262145)
            if len(raw)>262144:raise FetchError('Response too large')
            value=json.loads(raw)
            if not isinstance(value,dict):raise FetchError('Invalid response')
            return value
    except urllib.error.HTTPError as error:
        if error.code==404:error.close();return None
        if error.code==429:
            try:delay=float(error.headers.get('Retry-After') or 300)
            except (TypeError,ValueError):delay=300
            error.close();raise FetchError('Rate limited',rules.number(delay,0,86400) or 300) from None
        error.close();raise FetchError('Service unavailable') from None
    except (OSError,ValueError):raise FetchError('Service unavailable') from None


def enabled(addon):return addon.getSetting('episode_timing_lookup')!='false'


def enqueue(addon,item,duration=0):
    if not enabled(addon):return False
    try:return Store(addon).queue(rules.identity(item) or rules.clean_identity(item),duration)
    except TimingError:return False


class Worker:
    def __init__(self,addon,transport=fetch):self.addon=addon;self.store=Store(addon);self.transport=transport
    def call(self,provider,query):
        if not self.store.reserve(provider):raise FetchError('Request budget / retry wait')
        try:return self.transport(provider,query)
        except FetchError as error:
            self.store.backoff(provider,error.delay);raise
    def tick(self):
        if not enabled(self.addon):return
        job=self.store.claim()
        if not job:return
        try:
            item=rules.clean_identity(json.loads(job['item']))
            if not item:return
            for provider in ('TheIntroDB','IntroDB'):
                if not enabled(self.addon):return
                old,_=self.store.data(item)
                try:
                    rows=[]
                    if provider=='TheIntroDB':
                        query=rules.tidb_query(item);body=self.call(provider,dict(query,list_versions='true'))
                        if body is not None:
                            if not rules.tidb_identity(body,item):raise FetchError('Episode identity mismatch')
                            durations=rules.versions(body,item)
                            hint=job['duration'] or item['catalog_runtime']
                            durations=sorted(durations,key=lambda value:abs(value-hint))[:3]
                            if not durations:durations=[hint] if hint else []
                            queried=[]
                            for duration in durations:
                                if not enabled(self.addon):return
                                value=self.call(provider,dict(query,duration_ms=round(duration*1000)))
                                queried.append(duration)
                                if value is None:continue
                                if not rules.tidb_identity(value,item):raise FetchError('Episode identity mismatch')
                                rows.extend(rules.parse_tidb(value,item))
                            # Retain still-fresh other duration groups after a
                            # lookup for a newly observed edit, with bounded rows.
                            rows.extend(row for row in old if row.get('provider')==provider and rules.number(row.get('runtime')) and not any(abs(row['runtime']-duration)<.5 for duration in queried))
                            seen=set();rows=[row for row in rows if not (json.dumps(row,sort_keys=True) in seen or seen.add(json.dumps(row,sort_keys=True)))][:60]
                    elif item.get('imdb_id'):
                        body=self.call(provider,{k:item[k] for k in ('imdb_id','season','episode')})
                        if body is not None:
                            if body.get('imdb_id')!=item['imdb_id'] or body.get('season')!=item['season'] or body.get('episode')!=item['episode']:raise FetchError('Episode identity mismatch')
                            rows=rules.parse_introdb(body,item)
                    self.store.save(item,provider,rows,'Ready' if rows else 'No usable timing data',7*86400 if rows else 86400)
                except FetchError as error:
                    # A temporary failure never replaces a previous good result.
                    if not any(row.get('provider')==provider for row in old):self.store.save(item,provider,[],error.status,120)
        finally:self.store.finish(job)


def start(addon,monitor):
    def run():
        worker=Worker(addon)
        while not monitor.waitForAbort(1):
            try:worker.tick()
            except (TimingError,ValueError,TypeError,KeyError):pass
    thread=threading.Thread(target=run,name='MDM-TimingLookup',daemon=True);thread.start();return thread


def annotate_sources(addon,rows):
    """Cached metadata only. Unknown file runtime gets no timing score."""
    rows=[dict(row,extra={k:v for k,v in (row.get('extra') or {}).items() if k not in ('timing_match','timing_delta_seconds')}) for row in rows]
    if not enabled(addon):return rows
    try:
        from resources.lib.playback.chapter_facts import fingerprint
        store=Store(addon);observed=store.durations();result=[];memo={}
        for row in rows:
            extra=dict(row.get('extra') or {});item=rules.identity(extra.get('item'));identity=fingerprint(row)
            duration=observed.get(identity) or rules.source_duration(row)
            if duration:extra['file_duration_seconds']=duration
            # Clear old decorations if the user disabled the feature or changed
            # sources/settings; never trust a scraped timing-match assertion.
            extra.pop('timing_match',None);extra.pop('timing_delta_seconds',None)
            if item and duration:
                cache_key=rules.key(item)
                if cache_key not in memo:memo[cache_key]=store.data(item)[0]
                match,_=rules.match(memo[cache_key],duration,'intro')
                if match:extra.update(timing_match=True,timing_delta_seconds=match['delta'])
            result.append(dict(row,extra=extra))
        return result
    except TimingError:return rows
