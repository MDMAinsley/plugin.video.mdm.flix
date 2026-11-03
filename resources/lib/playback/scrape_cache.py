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


def key(addon, item):
    settings = [addon.getSetting(name) for name in FLIX_SETTINGS]
    provider_id = 'script.mdm.link' if settings[0] == 'MDM Link' else 'script.module.cocoscrapers'
    provider = get_addon(provider_id)
    if not provider:
        return None
    if provider_id == 'script.mdm.link':
        provider_settings = json.dumps([provider.getSetting(name) for name in LINK_SETTINGS]).encode()
    else:
        try:
            path = os.path.join(xbmcvfs.translatePath(provider.getAddonInfo('profile')), 'settings.xml')
            with open(path, 'rb') as stream:
                provider_settings = stream.read(128 * 1024 + 1)
            if len(provider_settings) > 128 * 1024:
                return None
        except FileNotFoundError:
            provider_settings = b''
        except (OSError, TypeError):
            return None
    identity = [item.get(name) for name in ('media_type', 'tmdb_id', 'season', 'episode', 'imdb_id')]
    if not identity[1]:
        return None
    context = json.dumps([identity, settings, provider.getAddonInfo('version')])
    return hashlib.sha256(context.encode('utf8') + b'\0' + provider_settings).hexdigest()


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
