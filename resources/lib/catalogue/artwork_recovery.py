"""Recover visible title artwork outside Home's directory requests."""
import json
import re
from threading import Thread
import time

import xbmc
import xbmcgui

from resources.lib.catalogue.tmdb import TMDB, CatalogueError, number
from resources.lib import device_policy
from resources.lib.home_rows import invalidate


SLOTS = ('continue', 'next', 'my_list', 'progress', 'movie', 'tv')
PROPERTY = 'mdm_artwork_requests_'
NEXT_PROPERTY = 'mdm_next_episode_requests'
IMAGE = re.compile(r'https://image\.tmdb\.org/t/p/[A-Za-z0-9_-]+(/[A-Za-z0-9._-]{1,200})')


def resized(value, size):
    match = IMAGE.fullmatch(value) if isinstance(value, str) else None
    return TMDB.image(match[1], size) if match else ''


def enrich(addon, core, media, identifier, images):
    """Use saved or cached metadata immediately. Return a request if incomplete."""
    from resources.lib.catalogue.browse import artwork

    light = device_policy.artwork_mode(addon)
    result = {name: resized(images.get(name), size) for name, size in
              (('poster', 'w342' if light else 'w500'), ('thumb', 'w300' if light else 'w500'), ('fanart', 'w1280'))}
    if light:
        result['fanart'] = ''
    if core is not None:
        try:
            raw = TMDB(addon, core, cache_only=True).details(media, identifier)
            if raw['id'] != identifier:
                raise CatalogueError('Artwork identity mismatch')
            cached = artwork(raw, addon=addon)
            result['poster'] = cached.get('poster') or result['poster']
            result['fanart'] = cached.get('fanart') or result['fanart']
            result['thumb'] = result['thumb'] or cached.get('thumb', '')
        except CatalogueError:
            pass
    result['thumb'] = result['thumb'] or result['poster']
    result['icon'] = result['poster'] or 'DefaultVideo.png'
    missing = not result['poster'] or not light and not result['fanart']
    return result, (media, identifier) if missing else None


def request(slot, identities):
    if slot in SLOTS:
        # Slots belong to separate rows, so concurrent directory requests cannot
        # overwrite another row's pending titles. Only public catalogue IDs.
        values = list(dict.fromkeys(identity for identity in identities if identity))[:12]
        xbmcgui.Window(10000).setProperty(PROPERTY + slot, json.dumps(values))


def request_next(episodes):
    xbmcgui.Window(10000).setProperty(NEXT_PROPERTY,json.dumps(list(dict.fromkeys(episodes))[:12]))


def pending_next():
    raw=xbmcgui.Window(10000).getProperty(NEXT_PROPERTY)
    try:
        values=json.loads(raw) if raw and len(raw)<=2048 else []
        return [(number(row[0],1),number(row[1],1),number(row[2],1))
                for row in values[:12] if isinstance(row,list) and len(row)==3]
    except (ValueError,TypeError,CatalogueError):
        return []


def pending():
    result = []
    window = xbmcgui.Window(10000)
    for slot in SLOTS:
        raw = window.getProperty(PROPERTY + slot)
        if not raw or len(raw) > 8192:
            continue
        try:
            values = json.loads(raw)
            if not isinstance(values, list):
                continue
            for value in values[:12]:
                if isinstance(value, list) and len(value) == 2 and value[0] in ('movie', 'tv'):
                    identity = value[0], number(value[1], 1)
                    if identity not in result:
                        result.append(identity)
        except (ValueError, TypeError, CatalogueError):
            continue
    return result


class Worker:
    def __init__(self, addon, core):
        self.addon, self.core = addon, core
        self.due = {}
        self.next_due = {}

    def warm_next(self):
        from resources.lib.playback.episode_ui import following
        from resources.lib.playback.progress import ProgressError
        from resources.lib.playback.viewing import Viewing
        now=time.monotonic()
        episodes=pending_next()
        self.next_due={item:due for item,due in self.next_due.items() if item in episodes}
        episode=next((item for item in episodes if self.next_due.get(item,0)<=now),None)
        if not episode:return
        self.next_due[episode]=now+300
        try:
            client=TMDB(self.addon,self.core)
            if not client.configured:return
            target=following(client,*episode,watched=Viewing(self.addon).watched_keys())
        except (CatalogueError,ProgressError):
            return
        if target:
            invalidate('continue')
            path=xbmc.getInfoLabel('Container.FolderPath')
            if path.startswith('plugin://plugin.video.mdm.flix/') and 'action=next_episodes' in path:
                xbmc.executebuiltin('Container.Refresh')

    def tick(self):
        now = time.monotonic()
        titles = pending()
        self.due = {identity: due for identity, due in self.due.items() if identity in titles}
        identity = next((identity for identity in titles if self.due.get(identity, 0) <= now), None)
        if identity is None:
            return
        media, identifier = identity
        client = TMDB(self.addon, self.core)
        if not client.configured:
            self.due[identity] = now + 300
            return
        marker = f'plugin.video.mdm.flix:artwork_retry:{media}:{identifier}'
        if self.core.cache.get_cache(marker):
            self.due[identity] = now + 300
            return
        self.due[identity] = now + 300
        self.core.cache.set_cache(marker, True, ttl=300)
        try:
            raw = client.details(media, identifier)
            if raw['id'] != identifier:
                return
        except CatalogueError:
            return
        self.due[identity] = time.monotonic() + 3600
        if TMDB.image(raw.get('poster_path')) or TMDB.image(raw.get('backdrop_path')):
            for slot in ('continue', 'my_list'):
                invalidate(slot)
            window = xbmcgui.Window(10000)
            window.setProperty('mdm_artwork_revision', str(time.monotonic_ns()))
            path = xbmc.getInfoLabel('Container.FolderPath')
            if path.startswith('plugin://plugin.video.mdm.flix/') and any(
                    'action=' + action in path for action in ('continue_watching', 'viewing_history', 'library_view', 'library_home_list')):
                xbmc.executebuiltin('Container.Refresh')


def start(addon, monitor):
    def run():
        from resources.lib.bootstrap import _load_core

        core = _load_core()
        if core is None:
            return
        worker = Worker(addon, core)
        while not monitor.waitForAbort(1):
            if xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):
                continue
            try:
                worker.warm_next()
                worker.tick()
            except (RuntimeError, OSError, ValueError, TypeError):
                continue

    thread = Thread(target=run, name='MDM-ArtworkRecovery', daemon=True)
    thread.start()
    return thread
