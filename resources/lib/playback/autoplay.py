"""Bounded sequential resolution, respecting current filters and failure classes."""
from resources.lib.playback import resolution_report
from itertools import islice
import xbmc
import xbmcgui
import time
from mdmlink import autoplay_context
from mdmlink.models import magnet_hash
from mdmlink.errors import PlaybackError, Cancelled, SourceFailure, SourcePreparing, SourceNotReady, AutoplayBudgetExpired
from resources.lib.catalogue.tmdb import CatalogueError
from resources.lib.playback.selection import sort_sources, with_fallback
from resources.lib.providers.manager import auto



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
        started=time.monotonic()
        rows = search(addon, core, log, params)
        item = (rows[0].get('extra') or {}).get('item') if rows else None
        fallback = None
        if auto(addon) and item and rows[0].get('provider_id') == 'mdm_link':
            def fallback():
                if xbmc.Monitor().abortRequested():
                    raise Cancelled('Playback cancelled.')
                autoplay_context.check()
                try:
                    return search(addon, core, log, dict(params, refresh='0'), fallback_item=item)
                except (Cancelled, AutoplayBudgetExpired):
                    raise
                except PlaybackError:
                    return []

        from resources.lib.playback import timing_match,stream_match,timing_rules
        if timing_match.enabled(addon) and rows and timing_rules.identity((rows[0].get('extra') or {}).get('item')):
            previous=stream_match.read(addon).get('run_id')
            try:
                chosen=stream_match.compare(addon,sort_sources(rows,addon),lambda source,attempt:resolve(source,addon,core,log,attempt=attempt),xbmc.Monitor().abortRequested,search_seconds=time.monotonic()-started,fallback=fallback)
            finally:
                latest=stream_match.read(addon)
                if latest.get('run_id')!=previous:
                    for key in ('attempted','failed','not_ready'):report[key]=latest.get(key,0)
                    report['duplicate_skipped']=latest.get('duplicates',0)
            if not chosen:
                save('sources_failed')
                raise PlaybackError('No timing-compatible stream was ready within the comparison limit. Open Timing match report for runtimes/rejections, refresh sources, or choose a source manually.')
            selected,url,match,match_report=chosen
            from resources.lib.playback.tracking import source as tracking_source
            with tracking_source(selected,addon,params.get('episode_chain')):
                play_url(url,selected.get('label','MDM Flix'))
            report['provider'] = selected.get('provider_id')
            handed_off=True;save('handoff')
            if match['score']<70:xbmcgui.Dialog().notification('MDM Flix','Playing an available stream; no intro timing match was established.',xbmcgui.NOTIFICATION_INFO,4000)
            return
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
        limit = attempts(addon) if fallback else min(attempts(addon), len(unique))
        monitor = xbmc.Monitor()
        last_failure = None

        def alternate():
            for source in fallback():
                url = source.get('url', '')
                key = magnet_hash(url) or url
                if key in seen:
                    report['duplicate_skipped'] += 1
                    continue
                seen.add(key)
                yield source

        with autoplay_context.bounded(75):
            candidates = with_fallback(unique, alternate if fallback else None)
            for index, source in enumerate(islice(candidates, limit), 1):
                autoplay_context.check()
                if monitor.abortRequested():
                    raise Cancelled("Playback cancelled.")
                # Recheck current preferences in case they changed since search.
                if not sort_sources([source], addon):
                    continue
                report['provider'] = source.get('provider_id')
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
                with tracking_source(source, addon, params.get('episode_chain')):
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
            if params.get('episode_chain'):
                from resources.lib.playback.next_prompt import clear_chain
                clear_chain(params['episode_chain'])
            failed()
