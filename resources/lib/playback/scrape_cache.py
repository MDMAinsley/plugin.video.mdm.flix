"""Recent scrape results stored only in Kodi's in-memory Home window."""
import hashlib
import json
import os

import xbmcgui
import xbmcvfs

from resources.lib.kodi_addons import get_addon

PROPERTY = 'plugin.video.mdm.flix.scrapes.v1'
MAX_BYTES = 512 * 1024
MAX_SEARCHES = 4
FLIX_SETTINGS = (
    'scraper_provider', 'alldebrid_enabled', 'alldebrid_api_key',
    'device_quality_max', 'device_unknown_quality', 'device_max_size_gib',
    'device_unknown_size', 'device_connection_mbps', 'device_unknown_bitrate',
    'device_slow_sources', 'device_source_order', 'device_search_timeout',
    'device_request_timeout', 'device_workers',
)
LINK_SETTINGS = (
    'source_mode', 'alldebrid_enabled', 'alldebrid_api_key', 'provider_archive',
    'provider_torrentio', 'device_quality_max', 'device_unknown_quality',
    'device_max_size_gib', 'device_unknown_size', 'device_connection_mbps',
    'device_unknown_bitrate', 'device_slow_sources', 'device_source_order',
    'device_search_timeout', 'device_request_timeout', 'device_workers',
) + tuple(f'provider_stream_{slot}_{field}' for slot in range(1, 4) for field in ('enabled', 'url'))


def key(addon, item, fallback=False):
    settings = [addon.getSetting(name) for name in FLIX_SETTINGS]
    mode = settings[0] or 'Auto'
    provider_ids = {
        'Auto': ('script.mdm.link', 'script.module.cocoscrapers'),
        'MDM Link': ('script.mdm.link',),
        'CocoScrapers': ('script.module.cocoscrapers',),
    }.get(mode, ())
    identity = [item.get(name) for name in ('media_type', 'tmdb_id', 'season', 'episode', 'imdb_id')]
    if not identity[1]:
        return None
    providers = []
    for provider_id in provider_ids:
        provider = get_addon(provider_id)
        if not provider:
            continue
        if provider_id == 'script.mdm.link':
            data = json.dumps([provider.getSetting(name) for name in LINK_SETTINGS]).encode()
        else:
            try:
                path = os.path.join(xbmcvfs.translatePath(provider.getAddonInfo('profile')), 'settings.xml')
                with open(path, 'rb') as stream:
                    data = stream.read(128 * 1024 + 1)
                if len(data) > 128 * 1024:
                    return None
            except FileNotFoundError:
                data = b''
            except (OSError, TypeError):
                return None
        providers.append([provider_id, provider.getAddonInfo('version'), hashlib.sha256(data).hexdigest()])
    if not providers:
        return None
    context = json.dumps([identity, settings, providers, fallback])
    return hashlib.sha256(context.encode('utf8')).hexdigest()


def _read(window):
    raw = window.getProperty(PROPERTY)
    value = json.loads(raw) if raw and len(raw) <= MAX_BYTES else {}
    return value if isinstance(value, dict) else {}


def get(cache_key):
    if not cache_key:
        return None
    try:
        rows = _read(xbmcgui.Window(10000)).get(cache_key)
        if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
            return rows
    except (AttributeError, RuntimeError, ValueError):
        pass
    return None


def put(cache_key, rows):
    if not cache_key or not rows:
        return
    try:
        window = xbmcgui.Window(10000)
        entries = _read(window)
        entries.pop(cache_key, None)
        entries[cache_key] = rows
        while entries:
            encoded = json.dumps(entries, separators=(',', ':'))
            if len(entries) <= MAX_SEARCHES and len(encoded) <= MAX_BYTES:
                window.setProperty(PROPERTY, encoded)
                return
            entries.pop(next(iter(entries)))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def forget(cache_key):
    if not cache_key:
        return
    try:
        window = xbmcgui.Window(10000)
        entries = _read(window)
        if entries.pop(cache_key, None) is not None:
            window.setProperty(PROPERTY, json.dumps(entries, separators=(',', ':')))
    except (AttributeError, RuntimeError, ValueError):
        pass


def clear():
    try:
        xbmcgui.Window(10000).clearProperty(PROPERTY)
    except (AttributeError, RuntimeError):
        pass
