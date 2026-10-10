from resources.lib.constants import PLAYBACK_MODE_AUTOPLAY, PLAYBACK_MODE_SOURCE_SELECT
from resources.lib.playback.files import web_url
import re


def get_playback_mode(addon):
    return PLAYBACK_MODE_AUTOPLAY if addon.getSetting('playback_mode')=='Autoplay' else PLAYBACK_MODE_SOURCE_SELECT


def usable(source):
    if not isinstance(source,dict): return False
    url=source.get('url')
    magnet = isinstance(url,str) and re.search(r'^magnet:\?xt=urn:btih:(?:[0-9a-fA-F]{40}|[a-zA-Z2-7]{32})(?:&|$)',url) and not any(c in url for c in ('\r','\n','\x00'))
    return isinstance(url,str) and (web_url(url) or magnet and bool(source.get('debrid')))


def sort_sources(sources):
    quality={'4K':500,'2160p':500,'1080p':400,'720p':300,'480p':200,'SD':100,'CAM':10,'Unknown':0}
    # Debrid priority is absolute, then sort by quality within each group.
    return sorted([s for s in sources or [] if usable(s)],key=lambda s:(bool(s.get('debrid')),quality.get(s.get('quality'),0)),reverse=True)


def pick_best_source(sources):
    rows=sort_sources(sources)
    return rows[0] if rows else None
