import sys
import xbmc
import xbmcaddon

from resources.lib.constants import ADDON_ID


def _load_core():
    try:
        import mdmcore
        return mdmcore
    except Exception:
        xbmc.log("[MDM Flix] Failed to import script.mdm.core / mdmcore", xbmc.LOGERROR)
        return None


def run():
    addon = xbmcaddon.Addon(ADDON_ID)
    core = _load_core()

    if core:
        try:
            log = core.logger.get_logger("plugin.video.mdm.flix")
            log.info("MDM Flix bootstrap started")
        except Exception:
            xbmc.log("[MDM Flix] Core loaded but logger failed", xbmc.LOGWARNING)
            log = None
    else:
        log = None

    from resources.lib.router import Router

    router = Router(
        addon=addon,
        core=core,
        log=log,
        argv=sys.argv,
    )
    router.dispatch()