"""Offer the optional Android search helper through the device installer."""
import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.catalogue.android_search import HELPER

DOWNLOADER = 'com.esaba.downloader'
AMAZON_STORE = 'com.amazon.venezia'
DOWNLOAD_URL = ('https://raw.githubusercontent.com/MDMAinsley/plugin.video.mdm.flix/main/'
                'resources/android/mdm-flix-search-1.4.apk')
ACTION = 'RunPlugin(plugin://plugin.video.mdm.flix/?action=voice_search_setup&automatic=1)'
TITLE = 'MDM Flix Voice Search'
OFFERED = 'MDM.Flix.VoiceSetupOffered'


def enabled(addon):
    return addon.getSetting('device_voice_search') == 'true'


class WatchSetting:
    def __init__(self, addon):
        self.addon = addon
        self.android = xbmc.getCondVisibility('System.Platform.Android')
        self.was_enabled = enabled(addon) if self.android else False

    def tick(self):
        if not self.android or xbmc.getCondVisibility('Window.IsActive(addonsettings)'):
            return
        current = enabled(self.addon)
        if current and not self.was_enabled:
            xbmc.executebuiltin(ACTION)
        elif self.was_enabled and not current:
            xbmcgui.Window(10000).clearProperty(OFFERED)
        self.was_enabled = current


def offer(addon, automatic=False):
    if not xbmc.getCondVisibility('System.Platform.Android') or (automatic and not enabled(addon)):
        return
    home = xbmcgui.Window(10000)
    if automatic and home.getProperty(OFFERED):
        return
    _, packages = xbmcvfs.listdir('androidapp://sources/apps/')
    dialog = xbmcgui.Dialog()
    if automatic and HELPER in packages:
        return
    home.setProperty(OFFERED, '1')
    if not dialog.yesno(TITLE, 'Download the latest MDM Flix Search helper to use the remote microphone. '
                        'Approve Install on the device, then return to Kodi.',
                        nolabel='Later', yeslabel='Download now'):
        return
    if DOWNLOADER in packages:
        xbmc.executebuiltin(f'StartAndroidActivity({DOWNLOADER},android.intent.action.VIEW,,downloader://{DOWNLOAD_URL})')
    elif AMAZON_STORE in packages:
        if dialog.yesno(TITLE, 'Install Downloader by AFTVnews from the Amazon Appstore. Then return to '
                        'Device tuning and select Install or update MDM Flix Search helper again.',
                        nolabel='Later', yeslabel='Open Appstore'):
            xbmc.executebuiltin(f'StartAndroidActivity({AMAZON_STORE},android.intent.action.VIEW,,'
                                f'amzn://apps/android?p={DOWNLOADER})')
    else:
        dialog.ok(TITLE, 'Open this address in Downloader by AFTVnews or an APK-capable browser on the device:\n\n'
                  + DOWNLOAD_URL)
