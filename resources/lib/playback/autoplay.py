"""Bounded sequential resolution, respecting current filters and failure classes."""
import json
import xbmc
import xbmcgui
from mdmlink import autoplay_context
from mdmlink.models import magnet_hash
from mdmlink.errors import PlaybackError, Cancelled, SourceFailure, SourcePreparing, AutoplayBudgetExpired
from resources.lib.catalogue.tmdb import CatalogueError
from resources.lib.playback.selection import sort_sources

STATUSES = {"resolving", "resolved", "no_sources", "sources_failed", "stopped", "preparing", "budget", "cancelled", "unexpected"}


def attempts(addon):
    value = addon.getSetting("autoplay_attempts") or "3"
    return int(value) if value in ("1", "2", "3") else 3


def diagnostic(addon):
    try:
        value = json.loads(addon.getSetting("last_autoplay_summary") or "{}")
        if value.get("status") not in STATUSES:
            return {}
        if any(type(value.get(key)) is not int or not 0 <= value[key] <= bound
               for key, bound in (("attempted", 3), ("failed", 3), ("duplicate_skipped", 10000))):
            return {}
        return {key: value[key] for key in ("status", "attempted", "failed", "duplicate_skipped")}
    except Exception:
        return {}


def run(nav, addon, core, log, params, search, resolve, play_url, failed):
    report = {"status": "resolving", "attempted": 0, "failed": 0, "duplicate_skipped": 0}
    handed_off = False
    def save(status):
        report["status"] = status
        try:
            addon.setSetting("last_autoplay_summary", json.dumps(report, sort_keys=True))
        except Exception:
            pass  # Diagnostic storage must not prevent playback.
    save("resolving")
    try:
        rows = search(addon, core, log, params)
        unique = []; seen = set()
        for row in sort_sources(rows, addon):
            url = row.get("url", "")
            key = magnet_hash(url) or url
            if key in seen:
                report["duplicate_skipped"] += 1
                continue
            seen.add(key); unique.append(row)
        if not unique:
            save("no_sources")
            raise PlaybackError("No sources remain under your current provider, quality, size and connection preferences.")
        limit = min(attempts(addon), len(unique))
        monitor = xbmc.Monitor()
        last_failure = None
        with autoplay_context.bounded(75):
            for index, source in enumerate(unique[:limit], 1):
                autoplay_context.check()
                if monitor.abortRequested():
                    raise Cancelled("Playback cancelled.")
                # Recheck current preferences in case they changed since search.
                if not sort_sources([source], addon):
                    continue
                report["attempted"] += 1; save("resolving")
                try:
                    url = resolve(source, addon, core, log, attempt=(index, limit))
                except Cancelled:
                    raise
                except SourceFailure as error:
                    last_failure = error; report["failed"] += 1
                    autoplay_context.check()
                    continue
                autoplay_context.check()
                if monitor.abortRequested():
                    raise Cancelled("Playback cancelled.")
                play_url(url, source.get("label", "MDM Flix"))
                handed_off = True; save("resolved")
                return
        save("sources_failed")
        reason = str(last_failure) if last_failure is not None else "The candidates no longer meet current preferences."
        raise PlaybackError("Autoplay could not resolve {} eligible source(s). {} Use Source Select to choose another.".format(report["attempted"], reason))
    except Cancelled:
        save("cancelled")
    except SourcePreparing as error:
        save("preparing"); xbmcgui.Dialog().ok("MDM Flix", str(error))
    except AutoplayBudgetExpired as error:
        save("budget"); xbmcgui.Dialog().ok("MDM Flix", str(error))
    except (PlaybackError, CatalogueError) as error:
        if report["status"] not in ("sources_failed", "no_sources"):
            save("stopped")
        xbmcgui.Dialog().ok("MDM Flix", str(error))
    except Exception:
        save("unexpected")
        if log:
            log.warning("Autoplay stopped after an unexpected resolution error")
        xbmcgui.Dialog().ok("MDM Flix", "Autoplay stopped after an unexpected error. Use Source Select or retry; no further source was attempted.")
    finally:
        if not handed_off:
            failed()
