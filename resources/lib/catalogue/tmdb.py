"""Application-authenticated TMDB requests using the shared Core helpers."""
from resources.lib import device_policy
import hashlib
import json
import re
from urllib.parse import urlencode


class CatalogueError(Exception):
    pass


def number(value, minimum=0, maximum=None):
    if not (type(value) is int or isinstance(value, str) and re.fullmatch(r"[0-9]+", value)):
        raise CatalogueError("This catalogue link is invalid. Return to Movies or TV Shows.")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise CatalogueError("This catalogue link is invalid. Return to Movies or TV Shows.")
    if isinstance(value, bool) or result < minimum or (maximum is not None and result > maximum):
        raise CatalogueError("This catalogue link is invalid. Return to Movies or TV Shows.")
    return result


class TMDB:
    BASE = "https://api.themoviedb.org/3/"

    def __init__(self, addon, core):
        self.core = core
        self.addon = addon
        self.token = addon.getSetting("tmdb_token").strip()
        self.key = addon.getSetting("tmdb_api_key").strip()
        language = addon.getSetting("tmdb_language").strip() or "en-GB"
        self.language = language if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", language) else "en-GB"

    @property
    def configured(self):
        return bool(self.token or self.key)

    @staticmethod
    def valid(data, field=None):
        return (isinstance(data, dict) and data.get("success") is not False and
                (isinstance(data.get(field), list) if field else type(data.get("id")) is int and data["id"] > 0))

    def request(self, endpoint, params=None, field=None, ttl=600):
        if not self.configured:
            raise CatalogueError("Enter your TMDB read token or API key in MDM Flix Settings → TMDB, then reopen this page.")
        if self.core is None:
            raise CatalogueError("MDM Core is unavailable. Enable or reinstall MDM Core 1.0.0 or later.")
        query = dict(params or {})
        query.setdefault("language", self.language)
        # Hash credentials and query for the cache key; plugin URLs contain no credentials.
        auth = self.token or self.key
        digest = hashlib.sha256(json.dumps([auth, endpoint, query], sort_keys=True).encode("utf-8")).hexdigest()
        cache_key = "plugin.video.mdm.flix:tmdb:" + digest
        try:
            cached = self.core.cache.get_cache(cache_key)
        except Exception:
            cached = None
        if self.valid(cached, field):
            return cached
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        else:
            query["api_key"] = self.key
        try:
            data = self.core.network.download_json(self.BASE + endpoint + "?" + urlencode(query), timeout=device_policy.integer(self.addon,"device_request_timeout",15,10,60), headers=headers)
        except Exception:
            data = None
        if not self.valid(data, field):
            raise CatalogueError("TMDB could not load this page. Check your credentials and internet connection, then try again.")
        try:
            self.core.cache.set_cache(cache_key, data, ttl=ttl)
        except Exception:
            pass  # A cache failure must not prevent browsing a valid response.
        return data

    def listing(self, media, kind, page=1, query=""):
        if media not in ("movie", "tv") or kind not in ("popular", "trending", "search"):
            raise CatalogueError("Unknown catalogue list.")
        params = {"page": number(page, 1, 500)}
        endpoint = media + "/popular"
        if kind == "trending":
            endpoint = "trending/" + media + "/week"
        elif kind == "search":
            endpoint = "search/" + media
            params.update(query=query, include_adult="false")
        return self.request(endpoint, params, field="results")

    def details(self, media, tmdb_id):
        if media not in ("movie", "tv"):
            raise CatalogueError("Unknown media type.")
        return self.request(media + "/" + str(number(tmdb_id, 1)), ttl=3600)

    def season(self, tmdb_id, season):
        return self.request("tv/{}/season/{}".format(number(tmdb_id, 1), number(season)), field="episodes", ttl=3600)

    @staticmethod
    def image(path, size="w500"):
        if not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9_.-]+", path):
            return ""
        return "https://image.tmdb.org/t/p/" + size + path
