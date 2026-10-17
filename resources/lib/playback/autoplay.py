"""Bounded sequential resolution, respecting current filters and failure classes."""
from resources.lib.playback import resolution_report
import xbmc
import xbmcgui
from mdmlink import autoplay_context
from mdmlink.models import magnet_hash
from mdmlink.errors import PlaybackError, Cancelled, SourceFailure, SourcePreparing, SourceNotReady, AutoplayBudgetExpired
from resources.lib.catalogue.tmdb import CatalogueError
from resources.lib.playback.selection import sort_sources



def attempts(addon):
    value = addon.getSetting("autoplay_attempts") or "3"
    return int(value) if value in ("1", "2", "3") else 3


def diagnostic(addon):
    return resolution_report.read(addon)


def run(nav, addon, core, log, params, search, resolve, play_url, failed):
    report = resolution_report.new(addon)
    handed_off = False
    def save(status):
        report["status"] = status
        return resolution_report.write(addon, report)
    def outcome(status, message):
        saved = save(status)
        summary = "\nAutoplay: {}. Tried {}, failed {}, not ready {}. Attempt {}.".format(
            status, report["attempted"], report["failed"], report["not_ready"], report["run_id"])
        if not saved:
            summary += "\nLatest diagnostic could not be saved; any older report is not this attempt."
        xbmcgui.Dialog().ok("MDM Flix", message + summary)
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
                    last_failure = error
                    if isinstance(error, SourceNotReady):
                        report["not_ready"] += 1
                    else:
                        report["failed"] += 1
                    autoplay_context.check()
                    continue
                autoplay_context.check()
                if monitor.abortRequested():
                    raise Cancelled("Playback cancelled.")
                from resources.lib.playback.tracking import source as tracking_source
                with tracking_source(source, addon):
                    play_url(url, source.get("label", "MDM Flix"))
                handed_off = True
                if not save("handoff"):
                    xbmcgui.Dialog().notification("MDM Flix", "Video handed to Kodi; latest diagnostic could not be saved.")
                return
        save("preparing" if report["not_ready"] == report["attempted"] and report["attempted"] else "sources_failed")
        reason = str(last_failure) if last_failure is not None else "The candidates no longer meet current preferences."
        raise PlaybackError("Autoplay could not resolve {} eligible source(s). {} Use Source Select to choose another.".format(report["attempted"], reason))
    except Cancelled:
        save("cancelled")
    except SourcePreparing as error:
        outcome("preparing", str(error))
    except AutoplayBudgetExpired as error:
        outcome("budget", str(error))
    except (PlaybackError, CatalogueError) as error:
        if report["status"] not in ("sources_failed", "no_sources", "preparing"):
            save("stopped")
        outcome(report["status"], str(error))
    except Exception:
        save("unexpected")
        if log:
            log.warning("Autoplay stopped after an unexpected resolution error")
        outcome("unexpected", "Autoplay stopped after an unexpected error. Use Source Select or retry; no further source was attempted.")
    finally:
        if not handed_off:
            failed()
