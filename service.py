import xbmcaddon
from resources.lib.playback.progress_service import run

if __name__=='__main__':
    run(xbmcaddon.Addon('plugin.video.mdm.flix'))
